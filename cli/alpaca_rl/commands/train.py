"""CLI commands for training workflow."""
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv
)

client = AlpacaClient()


@click.group()
def train():
    """Manage training runs and experiments."""


@train.command("start")
@click.option("--name", "-n", required=True, help="Training run name")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) to train on")
@click.option("--dataset", "-d", help="Dataset ID to use")
@click.option("--config", "-c", help="Path to training config file")
def start_training(name, symbols, dataset, config):
    """Start a new training run."""
    try:
        result = client.train_start(
            name=name,
            symbols=list(symbols),
            dataset_id=dataset,
            config_path=config
        )
        print_success(f"Training run '{name}' started")
        print_kv(result, title="Training Details")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("list")
@click.option("--status", type=click.Choice(["pending", "running", "completed", "failed"]))
@click.option("--pending-approval", is_flag=True, help="Show only runs pending approval")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_runs(status, pending_approval, output):
    """List training runs."""
    try:
        filters = {}
        if status:
            filters["status"] = status
        if pending_approval:
            filters["pending_approval"] = True
        
        runs = client.train_list(**filters)
        if output == "json":
            print_json(runs)
        else:
            print_table(
                runs,
                columns=["id", "name", "status", "symbols", "created_at", "approved"],
                title=f"Training Runs ({len(runs)} results)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("status")
@click.argument("run_id")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def training_status(run_id, output):
    """Get status of a training run."""
    try:
        status = client.train_status(run_id)
        if output == "json":
            print_json(status)
        else:
            print_kv(status, title=f"Run {run_id} Status")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("logs")
@click.argument("run_id")
@click.option("--follow", "-f", is_flag=True, help="Follow logs in real-time")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def training_logs(run_id, follow, lines):
    """Get logs for a training run."""
    try:
        logs = client.train_logs(run_id, follow=follow, lines=lines)
        click.echo(logs)
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@train.command("cancel")
@click.argument("run_id")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def cancel_training(run_id, yes):
    """Cancel a running training run."""
    if not yes:
        click.confirm(f"Cancel training run {run_id}?", abort=True)
    try:
        client.train_cancel(run_id)
        print_success(f"Training run {run_id} cancelled")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
