"""Output formatting utilities for the CLI."""
import json
from typing import Any

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def print_json(data: Any):
    """Pretty-print data as JSON."""
    console.print_json(json.dumps(data, default=str))


def print_table(rows: list[dict], columns: list[str] = None, title: str = None):
    """Print a list of dicts as a Rich table."""
    if not rows:
        console.print("[dim]No results.[/dim]")
        return

    cols = columns or list(rows[0].keys())
    table = Table(title=title, box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")

    for col in cols:
        table.add_column(col, overflow="fold")

    for row in rows:
        table.add_row(*[_fmt(row.get(col)) for col in cols])

    console.print(table)


def _fmt(value: Any) -> str:
    """Format a single cell value for display."""
    if value is None:
        return "[dim]-[/dim]"
    if isinstance(value, bool):
        return "[green]✓[/green]" if value else "[red]✗[/red]"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)[:60] + "…" if len(str(value)) > 60 else json.dumps(value, default=str)
    s = str(value)
    return s[:80] + "…" if len(s) > 80 else s


def print_success(msg: str):
    console.print(f"[green]✓[/green] {msg}")


def print_error(msg: str):
    console.print(f"[red]✗[/red] {msg}", err=True)


def print_warning(msg: str):
    console.print(f"[yellow]![/yellow] {msg}")


def print_kv(data: dict, title: str = None):
    """Print key-value pairs in a two-column table."""
    table = Table(title=title, box=box.SIMPLE, show_header=False)
    table.add_column("Key",   style="cyan", no_wrap=True)
    table.add_column("Value", overflow="fold")
    for k, v in data.items():
        table.add_row(str(k), _fmt(v))
    console.print(table)
