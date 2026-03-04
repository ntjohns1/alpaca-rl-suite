"""
alpaca-rl CLI — unified command-line interface for the alpaca-rl-suite.

Usage:
    alpaca-rl train start --name my-run --symbol SPY --symbol AAPL
    alpaca-rl train list --pending-approval
    alpaca-rl policy list --promoted
    alpaca-rl policy approve <policy_id>
    alpaca-rl backtest run --name test --symbol SPY
    alpaca-rl dataset preview --symbol SPY --rows 5
    alpaca-rl system status
"""
import click
from rich.console import Console

from .commands.train import train
from .commands.policy import policy
from .commands.backtest import backtest
from .commands.dataset import dataset
from .commands.system import system

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="alpaca-rl")
def cli():
    """Alpaca RL Suite — command-line interface."""


cli.add_command(train)
cli.add_command(policy)
cli.add_command(backtest)
cli.add_command(dataset)
cli.add_command(system)


if __name__ == "__main__":
    cli()
