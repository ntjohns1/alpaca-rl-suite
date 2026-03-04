"""CLI commands for training job management."""
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv
)

client = AlpacaClient()


@click.group()
def train():
    """Manage Kaggle and local training jobs."""


@train.command("start")
@click.option("--name", "-n", required=True, help="Job name")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) e.g. SPY")
@click.option("--mode", default="kaggle", type=click.Choice(["kaggle", "local"]), help="Training mode")
@click.option("--timesteps", "-t", default=500_000, help="Total training timesteps")
@click.option("--kernel-slug", default="alpaca-rl-training", help="Kaggle kernel slug")
@click.option("--dataset-slug", default=None, help="Kaggle dataset slug override")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def start_training(name, symbols, mode, timesteps, kernel_slug, dataset_slug, output):
    """Start a Kaggle training job."""
    payload = {
        "name": name,
        "symbols": list(symbols),
        "totalTimesteps": timesteps,
        "kernelSlug": kernel_slug,
    }
    if dataset_slug:
        payload["datasetSlug"] = dataset_slug

    try:
        result = client.kaggle_train(payload)
        if output == "json":
            print_json(result)
        else:
            print_success(f"Job started: {result['jobId']}")
            print_kv({
                "Job ID":  result["jobId"],
                "Status":  result["status"],
                "Name":    result["name"],
                "Monitor": f"alpaca-rl train status {result['jobId']}",
            })
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("status")
@click.argument("job_id")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def train_status(job_id, output):
    """Get status of a training job."""
    try:
        result = client.kaggle_get_job(job_id)
        if output == "json":
            print_json(result)
        else:
            print_kv({k: v for k, v in result.items() if k not in ("config", "metadata")})
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("list")
@click.option("--status", default=None, help="Filter by status")
@click.option("--pending-approval", is_flag=True, help="Show only jobs pending approval")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_jobs(status, pending_approval, output):
    """List training jobs."""
    approval_status = None
    if pending_approval:
        approval_status = "pending"
        status = "pending_approval"

    try:
        jobs = client.kaggle_list_jobs(status=status, approval_status=approval_status)
        if output == "json":
            print_json(jobs)
        else:
            print_table(
                jobs,
                columns=["id", "name", "status", "approval_status", "created_at"],
                title=f"Training Jobs ({len(jobs)} results)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("cancel")
@click.argument("job_id")
def cancel_job(job_id):
    """Cancel a running or pending training job."""
    try:
        result = client.kaggle_cancel_job(job_id)
        print_success(f"Job {job_id} cancelled")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("quota")
def quota():
    """Show Kaggle GPU quota."""
    try:
        result = client.kaggle_quota()
        print_kv(result, title="Kaggle GPU Quota")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
