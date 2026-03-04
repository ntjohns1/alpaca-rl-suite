"""HTTP client wrapper for all alpaca-rl-suite service APIs."""
import sys
from typing import Any, Optional

import requests
from rich.console import Console

from .config import Config

console = Console(stderr=True)


class APIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class AlpacaClient:
    """Thin wrapper around requests with consistent error handling."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.cfg = Config

    def _request(self, method: str, url: str, **kwargs) -> Any:
        try:
            resp = requests.request(method, url, timeout=self.timeout, **kwargs)
        except requests.exceptions.ConnectionError:
            console.print(f"[red]Connection refused:[/red] {url}")
            sys.exit(1)
        except requests.exceptions.Timeout:
            console.print(f"[red]Timeout:[/red] {url}")
            sys.exit(1)

        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise APIError(resp.status_code, detail)

        if resp.content:
            try:
                return resp.json()
            except Exception:
                return resp.content
        return None

    def get(self, url: str, **kwargs) -> Any:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Any:
        return self._request("POST", url, **kwargs)

    def delete(self, url: str, **kwargs) -> Any:
        return self._request("DELETE", url, **kwargs)

    # ─────────────────────────────────────────
    # Kaggle
    # ─────────────────────────────────────────
    def kaggle_train(self, payload: dict) -> dict:
        return self.post(f"{self.cfg.KAGGLE_URL}/kaggle/train", json=payload)

    def kaggle_list_jobs(self, status: Optional[str] = None, approval_status: Optional[str] = None) -> list:
        params = {}
        if status:
            params["status"] = status
        if approval_status:
            params["approval_status"] = approval_status
        return self.get(f"{self.cfg.KAGGLE_URL}/kaggle/jobs", params=params)

    def kaggle_get_job(self, job_id: str) -> dict:
        return self.get(f"{self.cfg.KAGGLE_URL}/kaggle/jobs/{job_id}")

    def kaggle_cancel_job(self, job_id: str) -> dict:
        return self.post(f"{self.cfg.KAGGLE_URL}/kaggle/jobs/{job_id}/cancel")

    def kaggle_approve(self, job_id: str, approved_by: str = "admin") -> dict:
        return self.post(
            f"{self.cfg.KAGGLE_URL}/kaggle/jobs/{job_id}/approve-promotion",
            json={"approved_by": approved_by},
        )

    def kaggle_reject(self, job_id: str, reason: Optional[str] = None) -> dict:
        return self.post(
            f"{self.cfg.KAGGLE_URL}/kaggle/jobs/{job_id}/reject-promotion",
            json={"reason": reason},
        )

    def kaggle_quota(self) -> dict:
        return self.get(f"{self.cfg.KAGGLE_URL}/kaggle/quota")

    # ─────────────────────────────────────────
    # Backtest
    # ─────────────────────────────────────────
    def backtest_run(self, payload: dict) -> dict:
        return self.post(f"{self.cfg.BACKTEST_URL}/backtest/run", json=payload)

    def backtest_get(self, report_id: str) -> dict:
        return self.get(f"{self.cfg.BACKTEST_URL}/backtest/{report_id}")

    def backtest_list(self, limit: int = 50) -> list:
        return self.get(f"{self.cfg.BACKTEST_URL}/backtest", params={"limit": limit})

    def backtest_charts(self, report_id: str) -> dict:
        return self.get(f"{self.cfg.BACKTEST_URL}/backtest/{report_id}/charts")

    # ─────────────────────────────────────────
    # Policies
    # ─────────────────────────────────────────
    def policy_list(self, promoted_only: bool = False, approval_status: Optional[str] = None) -> list:
        params: dict = {}
        if promoted_only:
            params["promoted_only"] = "true"
        if approval_status:
            params["approval_status"] = approval_status
        return self.get(f"{self.cfg.RL_TRAIN_URL}/rl/policies", params=params)

    def policy_get(self, policy_id: str) -> dict:
        return self.get(f"{self.cfg.RL_TRAIN_URL}/rl/policies/{policy_id}")

    def policy_approve(self, policy_id: str, approved_by: str = "admin") -> dict:
        return self.post(f"{self.cfg.RL_TRAIN_URL}/rl/policies/{policy_id}/approve",
                         params={"approved_by": approved_by})

    def policy_reject(self, policy_id: str, reason: Optional[str] = None) -> dict:
        return self.post(f"{self.cfg.RL_TRAIN_URL}/rl/policies/{policy_id}/reject",
                         params={"reason": reason})

    def policy_promote(self, policy_id: str, promoted_by: str = "admin") -> dict:
        return self.post(f"{self.cfg.RL_TRAIN_URL}/rl/policies/{policy_id}/promote",
                         params={"promoted_by": promoted_by})

    def policy_download(self, policy_id: str) -> bytes:
        return self.get(f"{self.cfg.RL_TRAIN_URL}/rl/policies/{policy_id}/download")

    def policy_delete(self, policy_id: str) -> None:
        return self.delete(f"{self.cfg.RL_TRAIN_URL}/rl/policies/{policy_id}")

    # ─────────────────────────────────────────
    # Datasets
    # ─────────────────────────────────────────
    def dataset_list(self) -> list:
        return self.get(f"{self.cfg.DATASET_URL}/datasets")

    def dataset_get(self, dataset_id: str) -> dict:
        return self.get(f"{self.cfg.DATASET_URL}/datasets/{dataset_id}")

    def dataset_export(self, symbols: list, format: str = "csv",
                       start_date: Optional[str] = None, end_date: Optional[str] = None) -> bytes:
        params: dict = {"symbols": symbols, "format": format}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.post(f"{self.cfg.DATASET_URL}/datasets/export", params=params)

    def dataset_preview(self, symbols: list, start_date: Optional[str] = None,
                        end_date: Optional[str] = None, rows: int = 20) -> dict:
        params: dict = {"symbols": symbols, "rows": rows}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.get(f"{self.cfg.DATASET_URL}/datasets/preview", params=params)

    def dataset_delete(self, dataset_id: str) -> None:
        return self.delete(f"{self.cfg.DATASET_URL}/datasets/{dataset_id}")

    # ─────────────────────────────────────────
    # System
    # ─────────────────────────────────────────
    def system_overview(self) -> dict:
        return self.get(f"{self.cfg.DASHBOARD_URL}/dashboard/overview")

    def system_services(self) -> dict:
        return self.get(f"{self.cfg.DASHBOARD_URL}/dashboard/services")

    def system_activity(self, limit: int = 20) -> dict:
        return self.get(f"{self.cfg.DASHBOARD_URL}/dashboard/activity", params={"limit": limit})
