"""CLI commands for system health and overview."""
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv, console
)

client = AlpacaClient()


@click.group()
def system():
    """System health and monitoring commands."""


@system.command("status")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def system_status(output):
    """Show system overview: service health + stats."""
    try:
        result = client.system_overview()
        if output == "json":
            print_json(result)
        else:
            sys_status = result.get("systemStatus", "unknown")
            color = "green" if sys_status == "healthy" else "red"
            console.print(f"\n[bold {color}]System: {sys_status.upper()}[/bold {color}]")

            # Service table
            services = result.get("services", [])
            print_table(services, columns=["service", "status", "latencyMs"], title="Service Health")

            # Stats
            stats = result.get("stats", {})
            print_kv({
                "Pending Approvals": result.get("pendingApprovals", 0),
                "Active Jobs":       result.get("activeJobs", 0),
                **stats,
            }, title="System Stats")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@system.command("services")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_services(output):
    """List health of all registered services."""
    try:
        result = client.system_services()
        if output == "json":
            print_json(result)
        else:
            print_table(
                result.get("services", []),
                columns=["service", "status", "latencyMs"],
                title="Service Health",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@system.command("activity")
@click.option("--limit", default=20, help="Number of events to show")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def system_activity(limit, output):
    """Show recent system activity."""
    try:
        result = client.system_activity(limit=limit)
        events = result.get("events", [])
        if output == "json":
            print_json(events)
        else:
            print_table(
                events,
                columns=["type", "name", "status", "subStatus", "timestamp"],
                title=f"Recent Activity ({len(events)} events)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
