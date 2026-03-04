"""CLI commands for dataset management."""
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv
)

client = AlpacaClient()


@click.group()
def dataset():
    """Manage training datasets."""


@dataset.command("list")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_datasets(output):
    """List all datasets."""
    try:
        datasets = client.dataset_list()
        if output == "json":
            print_json(datasets)
        else:
            print_table(
                datasets,
                columns=["id", "name", "symbols", "start_date", "end_date", "n_splits", "created_at"],
                title=f"Datasets ({len(datasets)} results)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@dataset.command("export")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) to export")
@click.option("--format", "-f", "fmt", default="csv", type=click.Choice(["csv", "parquet"]), help="Export format")
@click.option("--start", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--end", default=None, help="End date (YYYY-MM-DD)")
@click.option("--output", "-o", required=True, help="Output file path")
def export_dataset(symbols, fmt, start, end, output):
    """Export feature data for given symbols to a file."""
    try:
        data = client.dataset_export(list(symbols), format=fmt, start_date=start, end_date=end)
        if not isinstance(data, bytes):
            print_error("Unexpected non-binary response from export endpoint")
            raise SystemExit(1)
        with open(output, "wb") as f:
            f.write(data)
        print_success(f"Exported to {output} ({len(data):,} bytes)")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@dataset.command("preview")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) to preview")
@click.option("--start", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--end", default=None, help="End date (YYYY-MM-DD)")
@click.option("--rows", default=10, help="Number of preview rows")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def preview_dataset(symbols, start, end, rows, output):
    """Preview feature data for given symbols."""
    try:
        result = client.dataset_preview(list(symbols), start_date=start, end_date=end, rows=rows)
        if output == "json":
            print_json(result)
        else:
            meta = {k: v for k, v in result.items() if k != "data"}
            print_kv(meta, title="Dataset Preview")
            print_table(result.get("data", []))
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@dataset.command("delete")
@click.argument("dataset_id")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def delete_dataset(dataset_id, yes):
    """Delete a dataset manifest record."""
    if not yes:
        click.confirm(f"Delete dataset {dataset_id}?", abort=True)
    try:
        client.dataset_delete(dataset_id)
        print_success(f"Dataset {dataset_id} deleted")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
