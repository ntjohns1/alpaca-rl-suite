"""
Targeted tests for the train() background task in rl-train service.
Mocks all SB3, torch, and DB dependencies.
"""
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

import pandas as pd

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_conn():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


def _make_bars(n=400):
    return pd.DataFrame({
        "open":   [100.0] * n,
        "high":   [101.0] * n,
        "low":    [99.0]  * n,
        "close":  [100.5] * n,
        "volume": [1000]  * n,
    }, index=pd.date_range("2020-01-01", periods=n, freq="B"))


BASE_CONFIG = {
    "name": "test-run",
    "symbols": ["SPY"],
    "totalTimesteps": 100,
}


class TestTrainFunction:

    def _run_train(self, config=None, bars=None, extra_patches=None):
        cfg = config or BASE_CONFIG.copy()
        df = bars if bars is not None else _make_bars(400)

        mock_s3 = MagicMock()
        mock_model = MagicMock()
        mock_model.exploration_rate = 0.05
        mock_model.observation_space.shape = (11,)

        mock_cb = MagicMock()
        mock_cb.episode_metrics = [
            {"episode": i, "totalReward": float(i * 0.1), "steps": 252, "epsilon": 0.05}
            for i in range(1, 11)
        ]

        with patch("main.load_bars", return_value=df), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.update_run") as mock_update, \
             patch("main.save_policy_bundle") as mock_save, \
             patch("main.EpisodeMetricsCallback", return_value=mock_cb), \
             patch("main.DQN", return_value=mock_model), \
             patch("main.Monitor", return_value=MagicMock(
                 observation_space=MagicMock(shape=(11,))
             )), \
             patch("main.TradingEnvironment", return_value=MagicMock()), \
             patch("builtins.open", mock_open(read_data=b"fake-zip")):
            from main import train
            train("run-1", cfg)

        return mock_update, mock_save, mock_s3

    def test_completes_with_good_data(self):
        mock_update, mock_save, _ = self._run_train()
        final_status = mock_update.call_args_list[-1][0][1]
        assert final_status == "completed"

    def test_saves_policy_bundle_on_success(self):
        mock_update, mock_save, _ = self._run_train()
        mock_save.assert_called_once()
        call_args = mock_save.call_args[0]
        assert call_args[0] == "run-1"
        assert "models/run-1/policy_best.zip" in call_args[1]

    def test_uploads_model_zip_to_s3(self):
        mock_update, mock_save, mock_s3 = self._run_train()
        assert mock_s3.put_object.called
        keys = [c[1]["Key"] for c in mock_s3.put_object.call_args_list]
        assert any("policy_best.zip" in k for k in keys)

    def test_uploads_episode_history_to_s3(self):
        mock_update, mock_save, mock_s3 = self._run_train()
        keys = [c[1]["Key"] for c in mock_s3.put_object.call_args_list]
        assert any("episode_history.json" in k for k in keys)

    def test_marks_failed_when_insufficient_data(self):
        tiny_bars = _make_bars(50)  # < 300 required
        mock_update, _, _ = self._run_train(bars=tiny_bars)
        final_status = mock_update.call_args_list[-1][0][1]
        assert final_status == "failed"

    def test_marks_failed_on_exception(self):
        with patch("main.load_bars", side_effect=RuntimeError("DB error")), \
             patch("main.update_run") as mock_update:
            from main import train
            train("run-err", BASE_CONFIG.copy())
        mock_update.assert_called_with("run-err", "failed", {}, error="DB error")

    def test_final_metrics_includes_expected_keys(self):
        captured_metrics = {}

        def capture_save(run_id, s3_path, config, metrics):
            captured_metrics.update(metrics)

        mock_s3 = MagicMock()
        mock_model = MagicMock()
        mock_model.exploration_rate = 0.05
        mock_cb = MagicMock()
        mock_cb.episode_metrics = [
            {"episode": 1, "totalReward": 1.5, "steps": 252, "epsilon": 0.05}
        ]

        with patch("main.load_bars", return_value=_make_bars(400)), \
             patch("main.get_s3", return_value=mock_s3), \
             patch("main.update_run"), \
             patch("main.save_policy_bundle", side_effect=capture_save), \
             patch("main.EpisodeMetricsCallback", return_value=mock_cb), \
             patch("main.DQN", return_value=mock_model), \
             patch("main.Monitor", return_value=MagicMock(
                 observation_space=MagicMock(shape=(11,))
             )), \
             patch("main.TradingEnvironment", return_value=MagicMock()), \
             patch("builtins.open", mock_open(read_data=b"fake-zip")):
            from main import train
            train("run-2", BASE_CONFIG.copy())

        for key in ("symbol", "totalTimesteps", "totalEpisodes", "meanReward",
                    "maxReward", "finalEpsilon", "stateDim", "framework"):
            assert key in captured_metrics, f"Missing metric key: {key}"

    def test_uses_config_hyperparams(self):
        cfg = {**BASE_CONFIG, "learningRate": 5e-4, "batchSize": 128, "gamma": 0.95}
        captured_dqn_kwargs = {}

        def capture_dqn(**kwargs):
            captured_dqn_kwargs.update(kwargs)
            return MagicMock(exploration_rate=0.05)

        mock_cb = MagicMock()
        mock_cb.episode_metrics = []

        with patch("main.load_bars", return_value=_make_bars(400)), \
             patch("main.get_s3", return_value=MagicMock()), \
             patch("main.update_run"), \
             patch("main.save_policy_bundle"), \
             patch("main.EpisodeMetricsCallback", return_value=mock_cb), \
             patch("main.DQN", side_effect=capture_dqn), \
             patch("main.Monitor", return_value=MagicMock(
                 observation_space=MagicMock(shape=(11,))
             )), \
             patch("main.TradingEnvironment", return_value=MagicMock()), \
             patch("builtins.open", mock_open(read_data=b"fake")):
            from main import train
            train("run-3", cfg)

        assert captured_dqn_kwargs.get("learning_rate") == 5e-4
        assert captured_dqn_kwargs.get("batch_size") == 128
        assert captured_dqn_kwargs.get("gamma") == 0.95


class TestLoadBars:
    def _make_bars_with_date(self, n=100):
        """read_sql returns a df with a 'date' column; load_bars calls set_index('date')."""
        dates = pd.date_range("2020-01-01", periods=n, freq="B").date
        return pd.DataFrame({
            "date":   dates,
            "open":   [100.0] * n,
            "high":   [101.0] * n,
            "low":    [99.0]  * n,
            "close":  [100.5] * n,
            "volume": [1000]  * n,
        })

    def test_returns_dataframe(self):
        df = self._make_bars_with_date(100)
        with patch("main.get_conn") as mock_gc, \
             patch("pandas.read_sql", return_value=df):
            mock_conn, _ = _mock_conn()
            mock_gc.return_value = mock_conn
            from main import load_bars
            result = load_bars("SPY")
        assert len(result) == 100

    def test_sets_date_as_index(self):
        df = self._make_bars_with_date(50)
        with patch("main.get_conn") as mock_gc, \
             patch("pandas.read_sql", return_value=df):
            mock_conn, _ = _mock_conn()
            mock_gc.return_value = mock_conn
            from main import load_bars
            result = load_bars("SPY")
        assert result.index.name == "date"
