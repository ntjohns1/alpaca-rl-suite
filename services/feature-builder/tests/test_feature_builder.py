"""
Unit and API tests for the Feature Builder service.
All DB calls are mocked; no external services are required.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("ta")

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from feature_columns import ALL_FEATURE_COLS, SHARADAR_COLS, TECHNICAL_COLS


@pytest.fixture
def app_client():
    from main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _make_bars_df(n: int = 80, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    close = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n))
    return pd.DataFrame({
        "time": dates,
        "symbol": ["SPY"] * n,
        "open": close * rng.uniform(0.995, 1.0, n),
        "high": close * rng.uniform(1.0, 1.01, n),
        "low": close * rng.uniform(0.99, 1.0, n),
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n),
    })


def _make_bars_with_sharadar(n: int = 80, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = _make_bars_df(n=n, seed=seed)
    df["pe"] = rng.uniform(8, 35, n)
    df["pb"] = rng.uniform(1, 9, n)
    df["ps"] = rng.uniform(1, 12, n)
    df["evebitda"] = rng.uniform(4, 20, n)
    df["marketcap_log"] = rng.uniform(20, 28, n)
    df["roe"] = rng.uniform(-0.1, 0.4, n)
    df["roa"] = rng.uniform(-0.05, 0.2, n)
    df["debt_equity"] = rng.uniform(0, 3, n)
    df["revenue_growth"] = rng.uniform(-0.2, 0.5, n)
    df["fcf_yield"] = rng.uniform(-0.05, 0.15, n)
    return df


class _MockConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestComputeFeatures:
    def test_produces_all_20_feature_columns(self):
        from main import compute_features

        df = _make_bars_with_sharadar()
        feat_df = compute_features(df)

        assert not feat_df.empty
        for col in ALL_FEATURE_COLS:
            assert col in feat_df.columns, f"Missing feature column: {col}"

    def test_drops_rows_with_nan_technicals_but_preserves_nan_sharadar(self):
        from main import compute_features

        df = _make_bars_with_sharadar()
        df.loc[df.index[30], "close"] = np.nan
        df.loc[df.index[40], "pe"] = np.nan

        feat_df = compute_features(df)

        assert not feat_df.empty
        assert not feat_df[TECHNICAL_COLS].isnull().any().any()
        assert feat_df[SHARADAR_COLS].isnull().any().any()

    def test_winsorizes_valuation_columns(self):
        from main import compute_features

        df = _make_bars_with_sharadar()
        df.loc[df.index[-1], "pe"] = 50_000
        df.loc[df.index[-1], "pb"] = -50_000
        df.loc[df.index[-1], "ps"] = 10_000
        df.loc[df.index[-1], "evebitda"] = -10_000

        feat_df = compute_features(df)
        latest = feat_df.iloc[-1]

        assert latest["pe"] == 1000
        assert latest["pb"] == -1000
        assert latest["ps"] == 1000
        assert latest["evebitda"] == -1000


class TestSharadarMerge:
    def test_empty_sharadar_sources_fill_nan_columns(self):
        from main import merge_sharadar_features

        bars_df = _make_bars_df()
        empty_daily = pd.DataFrame(columns=["date", "ticker", "pe", "pb", "ps", "evebitda", "marketcap"])
        empty_fund = pd.DataFrame(columns=["calendardate", "ticker", "roe", "roa", "debt", "equity", "revenue", "fcf", "marketcap"])

        with patch("main.fetch_sharadar_daily", return_value=empty_daily), \
             patch("main.fetch_fundamentals", return_value=empty_fund):
            merged = merge_sharadar_features(bars_df, MagicMock(), "SPY")

        for col in SHARADAR_COLS:
            assert col in merged.columns
            assert merged[col].isna().all(), f"{col} should be NaN when SHARADAR is unavailable"


class TestStateVector:
    def test_returns_exactly_20_floats_and_maps_nan_to_zero(self):
        from main import build_state_vector

        row = pd.Series({col: float(i) for i, col in enumerate(ALL_FEATURE_COLS)})
        row["pe"] = np.nan
        row["roe"] = None

        vec = build_state_vector(row)

        assert len(vec) == len(ALL_FEATURE_COLS)
        assert all(isinstance(v, float) for v in vec)
        assert vec[ALL_FEATURE_COLS.index("pe")] == 0.0
        assert vec[ALL_FEATURE_COLS.index("roe")] == 0.0


class TestSafeFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (np.nan, None),
            (np.inf, None),
            (-np.inf, None),
            (1.25, 1.25),
            (3, 3.0),
        ],
    )
    def test_handles_edge_cases(self, value, expected):
        from main import _safe_float

        result = _safe_float(value)
        if expected is None:
            assert result is None
        else:
            assert result == expected


class TestApiEndpoints:
    def test_build_endpoint_computes_and_upserts_rows(self, app_client):
        bars = _make_bars_df()
        merged = _make_bars_with_sharadar()
        mock_conn = _MockConn()

        with patch("main.get_conn", return_value=mock_conn), \
             patch("main.fetch_bars", return_value=bars), \
             patch("main.merge_sharadar_features", return_value=merged), \
             patch("main.upsert_features") as mock_upsert:
            resp = app_client.post("/features/build", json={"symbols": ["SPY"], "days": 80})

        assert resp.status_code == 200
        body = resp.json()
        assert body["SPY"]["status"] == "ok"
        assert body["SPY"]["rows"] > 0
        mock_upsert.assert_called_once()

    def test_latest_endpoint_returns_state_vector_and_features(self, app_client):
        bars = _make_bars_df()
        merged = _make_bars_with_sharadar()
        mock_conn = _MockConn()

        with patch("main.get_conn", return_value=mock_conn), \
             patch("main.fetch_bars", return_value=bars), \
             patch("main.merge_sharadar_features", return_value=merged):
            resp = app_client.get("/features/latest/SPY")

        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "SPY"
        assert len(body["state_vector"]) == len(ALL_FEATURE_COLS)
        assert set(body["features"].keys()) == set(ALL_FEATURE_COLS)

    def test_availability_endpoint_returns_feature_and_bar_counts(self, app_client):
        mock_conn = _MockConn()
        read_results = [
            pd.DataFrame([{"feature_count": 41}]),
            pd.DataFrame([{"bar_count": 50}]),
        ]

        with patch("main.get_conn", return_value=mock_conn), \
             patch("pandas.read_sql", side_effect=read_results):
            resp = app_client.get(
                "/features/availability",
                params={"symbols": "SPY", "start_date": "2024-01-01", "end_date": "2024-03-31"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"SPY": {"feature_rows": 41, "bar_rows": 50}}
