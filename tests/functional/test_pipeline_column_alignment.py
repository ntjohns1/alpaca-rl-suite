"""
High-value column alignment tests for the 20-feature pipeline.
These tests avoid Docker and focus on contract drift across service boundaries.
"""
import ast
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
from unittest.mock import patch

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = ROOT / "services" / "shared"
FEATURE_BUILDER_PATH = ROOT / "services" / "feature-builder" / "main.py"
DATASET_BUILDER_PATH = ROOT / "services" / "dataset-builder" / "main.py"
KAGGLE_ORCH_PATH = ROOT / "services" / "kaggle-orchestrator" / "main.py"
TRADING_ENV_PATH = ROOT / "services" / "rl-train" / "trading_env.py"
MAIN_NOTEBOOK_PATH = ROOT / "kaggle" / "notebooks" / "alpaca-rl-training.ipynb"
KERNEL_SETUP_NOTEBOOK_PATH = ROOT / "kaggle" / "kernel-setup" / "alpaca-rl-training.ipynb"

sys.path.insert(0, str(SHARED_DIR))

from feature_columns import ALL_FEATURE_COLS, SHARADAR_COLS, TECHNICAL_COLS


def load_module(name: str, path: Path):
    _install_stubs()
    with _temporary_sys_path([str(path.parent), str(SHARED_DIR)]):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


def _make_pipeline_df(n: int = 120, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    df = pd.DataFrame({
        "time": dates,
        "symbol": ["SPY"] * n,
        "open": close * rng.uniform(0.995, 1.0, n),
        "high": close * rng.uniform(1.0, 1.01, n),
        "low": close * rng.uniform(0.99, 1.0, n),
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n),
        "pe": rng.uniform(8, 35, n),
        "pb": rng.uniform(1, 9, n),
        "ps": rng.uniform(1, 12, n),
        "evebitda": rng.uniform(4, 20, n),
        "marketcap_log": rng.uniform(20, 28, n),
        "roe": rng.uniform(-0.1, 0.4, n),
        "roa": rng.uniform(-0.05, 0.2, n),
        "debt_equity": rng.uniform(0, 3, n),
        "revenue_growth": rng.uniform(-0.2, 0.5, n),
        "fcf_yield": rng.uniform(-0.05, 0.15, n),
    })
    return df


def _load_notebook_code(path: Path) -> str:
    nb = json.loads(path.read_text())
    chunks = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        lines = []
        for line in cell.get("source", []):
            stripped = line.lstrip()
            if stripped.startswith("!") or stripped.startswith("%"):
                continue
            lines.append(line)
        chunks.append("".join(lines))
    return "\n\n".join(chunks)


@contextlib.contextmanager
def _temporary_sys_path(paths: list[str]):
    original = list(sys.path)
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        yield
    finally:
        sys.path[:] = original


def _extract_list_assignment(source: str, variable_name: str) -> list[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == variable_name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"Could not find assignment for {variable_name}")


def _install_stubs():
    if "observability" not in sys.modules:
        observability = types.ModuleType("observability")
        observability.setup_observability = lambda *args, **kwargs: None
        sys.modules["observability"] = observability

    if "boto3" not in sys.modules:
        boto3 = types.ModuleType("boto3")
        boto3.client = lambda *args, **kwargs: None
        sys.modules["boto3"] = boto3

    if "fastapi" not in sys.modules:
        fastapi = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code: int, detail=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class FastAPI:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, *args, **kwargs):
                return lambda fn: fn

            def post(self, *args, **kwargs):
                return lambda fn: fn

            def delete(self, *args, **kwargs):
                return lambda fn: fn

            def api_route(self, *args, **kwargs):
                return lambda fn: fn

        class BackgroundTasks:
            def add_task(self, *args, **kwargs):
                return None

        class Request:
            pass

        fastapi.FastAPI = FastAPI
        fastapi.BackgroundTasks = BackgroundTasks
        fastapi.HTTPException = HTTPException
        fastapi.Query = lambda default=None, **kwargs: default
        fastapi.Request = Request
        sys.modules["fastapi"] = fastapi

    if "fastapi.responses" not in sys.modules:
        responses = types.ModuleType("fastapi.responses")

        class Response:
            def __init__(self, content=None, media_type=None, headers=None):
                self.content = content
                self.media_type = media_type
                self.headers = headers or {}

        class StreamingResponse(Response):
            pass

        responses.Response = Response
        responses.StreamingResponse = StreamingResponse
        sys.modules["fastapi.responses"] = responses

    if "pydantic" not in sys.modules:
        pydantic = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        pydantic.BaseModel = BaseModel
        pydantic.Field = lambda default=None, **kwargs: default
        sys.modules["pydantic"] = pydantic

    if "psycopg2" not in sys.modules:
        psycopg2 = types.ModuleType("psycopg2")
        psycopg2.connect = lambda *args, **kwargs: _MockConn()
        sys.modules["psycopg2"] = psycopg2

    if "psycopg2.extras" not in sys.modules:
        extras = types.ModuleType("psycopg2.extras")
        extras.execute_values = lambda *args, **kwargs: None
        sys.modules["psycopg2.extras"] = extras


class _MockConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_feature_builder_compute_features_matches_shared_contract():
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
    module = load_module("feature_builder_main_contract", FEATURE_BUILDER_PATH)

    feat_df = module.compute_features(_make_pipeline_df())

    assert not feat_df.empty
    assert all(col in feat_df.columns for col in ALL_FEATURE_COLS)
    assert feat_df[TECHNICAL_COLS].isnull().sum().sum() == 0


def test_dataset_builder_fetch_features_sql_selects_all_20_features_and_ohlcv():
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
    module = load_module("dataset_builder_main_contract", DATASET_BUILDER_PATH)

    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        return pd.DataFrame()

    with patch.object(module.psycopg2, "connect", return_value=_MockConn()), \
         patch.object(module.pd, "read_sql", side_effect=fake_read_sql):
        module.fetch_features(["SPY"], "2024-01-01", "2024-03-31")

    sql = captured["sql"]
    for col in ALL_FEATURE_COLS + ["open", "high", "low", "close", "volume"]:
        assert col in sql, f"{col} missing from dataset-builder fetch SQL"


def test_kaggle_export_sql_selects_all_20_features_and_close():
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
    module = load_module("kaggle_orchestrator_contract", KAGGLE_ORCH_PATH)

    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        data = {
            "date": pd.date_range("2024-01-01", periods=320, freq="B"),
            "close": np.linspace(100, 130, 320),
        }
        for i, col in enumerate(ALL_FEATURE_COLS):
            data[col] = np.full(320, i, dtype=float)
        return pd.DataFrame(data)

    with patch.object(module, "get_conn", return_value=_MockConn()), \
         patch.object(module.pd, "read_sql", side_effect=fake_read_sql), \
         patch.object(pd.DataFrame, "to_csv", autospec=True) as mock_to_csv:
        result = module.export_training_dataset("SPY", "/tmp/fake.csv")

    sql = captured["sql"]
    for col in ALL_FEATURE_COLS + ["close"]:
        assert col in sql, f"{col} missing from kaggle export SQL"
    assert result["feature_version"] == "v2"
    mock_to_csv.assert_called_once()


def test_trading_env_precomputed_mode_uses_shared_columns():
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
    module = load_module("trading_env_contract", TRADING_ENV_PATH)

    assert module.DataSource.FEATURE_COLS == ALL_FEATURE_COLS
    ds = module.DataSource(
        df=pd.DataFrame({
            **{col: np.linspace(0.1, 1.0, 80) for col in ALL_FEATURE_COLS},
            "close": np.linspace(100, 110, 80),
        }, index=pd.date_range("2024-01-01", periods=80, freq="B")),
        feature_mode="precomputed",
    )
    assert ds.data.shape[1] == len(ALL_FEATURE_COLS)


def test_main_kaggle_notebook_feature_lists_match_shared_contract():
    source = _load_notebook_code(MAIN_NOTEBOOK_PATH)
    notebook_technical = _extract_list_assignment(source, "TECHNICAL_COLS")
    notebook_sharadar = _extract_list_assignment(source, "SHARADAR_COLS")

    assert notebook_technical == TECHNICAL_COLS
    assert notebook_sharadar == SHARADAR_COLS


def test_kernel_setup_notebook_feature_lists_match_shared_contract():
    source = _load_notebook_code(KERNEL_SETUP_NOTEBOOK_PATH)
    notebook_technical = _extract_list_assignment(source, "FEATURE_COLS")

    assert notebook_technical == ALL_FEATURE_COLS


def test_dataset_builder_parquet_schema_preserves_all_feature_columns():
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
    module = load_module("dataset_builder_schema_contract", DATASET_BUILDER_PATH)

    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=120, freq="B", tz="UTC"),
        "symbol": ["SPY"] * 120,
        **{col: np.linspace(0.0, 1.0, 120) for col in ALL_FEATURE_COLS},
        "open": np.linspace(100, 120, 120),
        "high": np.linspace(101, 121, 120),
        "low": np.linspace(99, 119, 120),
        "close": np.linspace(100, 120, 120),
        "volume": np.arange(120) + 1000,
    })

    captured_bytes = {}

    class MockS3:
        def put_object(self, Bucket, Key, Body):
            captured_bytes[Key] = Body

    with patch.object(module, "fetch_features", return_value=df), \
         patch.object(module, "get_s3", return_value=MockS3()), \
         patch.object(module, "register_manifest", return_value="dataset-1"):
        response = module.build_dataset(module.BuildDatasetRequest(
            name="contract-test",
            symbols=["SPY"],
            start_date="2024-01-01",
            end_date="2024-06-30",
            n_splits=2,
            train_frac=0.7,
        ))

    assert response["datasetId"] == "dataset-1"
    train_keys = [key for key in captured_bytes if key.endswith("train.parquet")]
    assert train_keys, "Expected at least one train parquet upload"

    import pyarrow.parquet as pq
    import io

    table = pq.read_table(io.BytesIO(captured_bytes[train_keys[0]]))
    parquet_cols = table.column_names
    for col in ALL_FEATURE_COLS:
        assert col in parquet_cols, f"{col} missing from exported parquet schema"
