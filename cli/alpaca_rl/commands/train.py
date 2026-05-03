"""CLI commands for training management."""
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv
)

_client = None


def _get_client() -> AlpacaClient:
    """Lazy client initialization to avoid expensive setup on `alpaca-rl --help`."""
    global _client
    if _client is None:
        _client = AlpacaClient()
    return _client


@click.group()
def train():
    """Manage training jobs on Kaggle."""


def _submit_training_job(name, symbols, kernel, timesteps, output):
    """Shared logic for submitting a training job."""
    payload = {
        "name": name,
        "symbols": list(symbols),
        "timesteps": timesteps,
    }
    if kernel:
        payload["kernel"] = kernel

    try:
        result = _get_client().kaggle_train(payload)
        if output == "json":
            print_json(result)
        else:
            job_id = result.get("jobId")
            if not job_id:
                print_error("Server returned success but no job ID")
                raise SystemExit(1)
            print_success(f"Training job submitted: {job_id}")
            print_kv({
                "Job ID":    job_id,
                "Status":    result.get("status", "-"),
                "Name":      result.get("name", "-"),
                "Check":     f"alpaca-rl train status {job_id}",
            })
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("kaggle")
@click.option("--name", "-n", required=True, help="Training run name")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) to train on")
@click.option("--kernel", required=True, help="Kaggle kernel slug (e.g., username/kernel-name)")
@click.option("--timesteps", default=100_000, type=int, help="Number of training timesteps")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def kaggle_train(name, symbols, kernel, timesteps, output):
    """Kick off a training run on Kaggle.
    
    Example:
        alpaca-rl train kaggle --name spy-1d-train --symbol SPY --kernel myuser/mykernel --timesteps 100000
    """
    _submit_training_job(name, symbols, kernel, timesteps, output)


@train.command("start")
@click.option("--name", "-n", required=True, help="Training run name")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) to train on")
@click.option("--kernel", help="Kaggle kernel slug (e.g., username/kernel-name)")
@click.option("--timesteps", default=100_000, type=int, help="Number of training timesteps")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def start_training(name, symbols, kernel, timesteps, output):
    """Start a training job (alias for 'kaggle' command).
    
    Example:
        alpaca-rl train start --name spy-1d-train --symbol SPY --symbol AAPL
    """
    _submit_training_job(name, symbols, kernel, timesteps, output)


@train.command("status")
@click.argument("job_id")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def job_status(job_id, output):
    """Poll status of a training job.
    
    Example:
        alpaca-rl train status <jobId>
    """
    try:
        result = _get_client().kaggle_get_job(job_id)
        if output == "json":
            print_json(result)
        else:
            print_kv({
                "Job ID":          result.get("id", "-"),
                "Name":            result.get("name", "-"),
                "Status":          result.get("status", "-"),
                "Approval Status": result.get("approval_status", "-"),
                "Error":           result.get("error") or "-",
            }, title=f"Training Job: {job_id}")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("list")
@click.option("--pending-approval", is_flag=True, help="Show only jobs pending approval")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_jobs(pending_approval, output):
    """List training jobs."""
    try:
        if pending_approval:
            results = _get_client().kaggle_list_jobs(status="pending_approval", approval_status="pending")
        else:
            results = _get_client().kaggle_list_jobs()
        
        if output == "json":
            print_json(results)
        else:
            print_table(
                results,
                columns=["id", "name", "status", "approval_status", "created_at"],
                title=f"Training Jobs ({len(results)} results)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("cancel")
@click.argument("job_id")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def cancel_job(job_id, output):
    """Cancel a training job."""
    try:
        result = _get_client().kaggle_cancel_job(job_id)
        if output == "json":
            print_json(result)
        else:
            print_success(f"Job {job_id} cancelled")
            print_kv({
                "Job ID": result.get("jobId", "-"),
                "Status": result.get("status", "-"),
            })
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("quota")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def show_quota(output):
    """Show Kaggle GPU quota usage."""
    try:
        result = _get_client().kaggle_quota()
        if output == "json":
            print_json(result)
        else:
            print_kv({
                "Username":      result.get("username", "-"),
                "GPU Quota":     f"{result.get('gpuQuota', 0)} hours/week",
                "GPU Used":      f"{result.get('gpuUsed', 0)} hours",
                "GPU Remaining": f"{result.get('gpuRemaining', 0)} hours",
            }, title="Kaggle GPU Quota")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
