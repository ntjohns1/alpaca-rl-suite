"""CLI configuration — loads API endpoint URLs from environment or .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Walk up the directory tree looking for a .env file
_here = Path(__file__).resolve()
for _parent in [_here.parent.parent.parent, _here.parent.parent.parent.parent]:
    _env = _parent / ".env"
    if _env.exists():
        load_dotenv(_env)
        break
else:
    load_dotenv()  # fall back to current directory


class Config:
    KAGGLE_URL   = os.getenv("KAGGLE_ORCHESTRATOR_URL", "http://localhost:8011")
    BACKTEST_URL = os.getenv("BACKTEST_URL",            "http://localhost:8001")
    RL_TRAIN_URL = os.getenv("RL_TRAIN_URL",            "http://localhost:8004")
    DATASET_URL  = os.getenv("DATASET_URL",             "http://localhost:8003")
    DASHBOARD_URL = os.getenv("DASHBOARD_URL",          "http://localhost:8020")

    @classmethod
    def all_urls(cls) -> dict:
        return {
            "kaggle-orchestrator": cls.KAGGLE_URL,
            "backtest":            cls.BACKTEST_URL,
            "rl-train":            cls.RL_TRAIN_URL,
            "dataset-builder":     cls.DATASET_URL,
            "dashboard":           cls.DASHBOARD_URL,
        }
