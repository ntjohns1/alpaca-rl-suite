"""CLI commands for backtest management."""
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv
)

client = AlpacaClient()


@click.group()
def backtest():
    """Run and review backtests."""


@backtest.command("run")
@click.option("--name", "-n", required=True, help="Backtest name")
@click.option("--symbol", "-s", "symbols", multiple=True, required=True, help="Symbol(s) to backtest")
@click.option("--policy-id", default=None, help="Policy ID to evaluate (omit for buy-and-hold baseline)")
@click.option("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
@click.option("--end", default="2024-12-31", help="End date (YYYY-MM-DD)")
@click.option("--capital", default=100_000.0, help="Initial capital")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def run_backtest(name, symbols, policy_id, start, end, capital, output):
    """Submit a backtest job."""
    payload = {
        "name": name,
        "symbols": list(symbols),
        "startDate": start,
        "endDate": end,
        "initialCapital": capital,
    }
    if policy_id:
        payload["policyId"] = policy_id

    try:
        result = client.backtest_run(payload)
        if output == "json":
            print_json(result)
        else:
            print_success(f"Backtest submitted: {result['reportId']}")
            print_kv({
                "Report ID": result["reportId"],
                "Status":    result["status"],
                "Check":     f"alpaca-rl backtest show {result['reportId']}",
            })
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@backtest.command("show")
@click.argument("report_id")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def show_backtest(report_id, output):
    """Show backtest results."""
    try:
        result = client.backtest_get(report_id)
        if output == "json":
            print_json(result)
        else:
            metrics = result.get("metrics") or {}
            print_kv({
                "Report ID":      report_id,
                "Status":         result["status"],
                "Avg Sharpe":     f"{metrics.get('avgSharpe', '-'):.3f}" if metrics.get("avgSharpe") else "-",
                "Avg Return":     f"{metrics.get('avgTotalReturn', 0)*100:.2f}%" if metrics.get("avgTotalReturn") else "-",
                "Avg Drawdown":   f"{metrics.get('avgMaxDrawdown', 0)*100:.2f}%" if metrics.get("avgMaxDrawdown") else "-",
                "Avg Win Rate":   f"{metrics.get('avgWinRate', 0)*100:.1f}%" if metrics.get("avgWinRate") else "-",
                "Charts":         f"alpaca-rl backtest charts {report_id}" if result["status"] == "completed" else "-",
            }, title="Backtest Results")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@backtest.command("list")
@click.option("--limit", default=20, help="Max results")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_backtests(limit, output):
    """List recent backtests."""
    try:
        results = client.backtest_list(limit=limit)
        if output == "json":
            print_json(results)
        else:
            print_table(
                results,
                columns=["id", "name", "status", "created_at"],
                title=f"Backtests ({len(results)} results)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@backtest.command("charts")
@click.argument("report_id")
def show_charts(report_id):
    """Show chart paths for a completed backtest."""
    try:
        result = client.backtest_charts(report_id)
        print_kv({
            "Report ID": report_id,
            "Symbols":   ", ".join(result.get("symbols", [])),
        })
        for symbol, path in result.get("chartPaths", {}).items():
            click.echo(f"  {symbol}: {path}")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
