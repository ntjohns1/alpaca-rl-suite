"""CLI commands for policy management."""
import sys
import click

from ..client import AlpacaClient, APIError
from ..utils.formatting import (
    print_json, print_table, print_success, print_error, print_kv
)

client = AlpacaClient()


@click.group()
def policy():
    """Manage trained policy bundles."""


@policy.command("list")
@click.option("--promoted", is_flag=True, help="Show only promoted policies")
@click.option("--approval-status", default=None, help="Filter by approval_status (pending/approved/rejected)")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def list_policies(promoted, approval_status, output):
    """List policy bundles."""
    try:
        policies = client.policy_list(promoted_only=promoted, approval_status=approval_status)
        if output == "json":
            print_json(policies)
        else:
            print_table(
                policies,
                columns=["id", "name", "version", "promoted", "approval_status", "created_at"],
                title=f"Policies ({len(policies)} results)",
            )
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@policy.command("show")
@click.argument("policy_id")
@click.option("--output", "-o", default="table", type=click.Choice(["table", "json"]))
def show_policy(policy_id, output):
    """Show details for a single policy."""
    try:
        result = client.policy_get(policy_id)
        if output == "json":
            print_json(result)
        else:
            print_kv({k: v for k, v in result.items() if k != "config"}, title="Policy Details")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@policy.command("approve")
@click.argument("policy_id")
@click.option("--by", default="admin", help="Who is approving")
def approve_policy(policy_id, by):
    """Approve a policy for promotion."""
    try:
        result = client.policy_approve(policy_id, approved_by=by)
        print_success(f"Policy {policy_id} approved by {by}")
        print_kv(result)
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@policy.command("reject")
@click.argument("policy_id")
@click.option("--reason", default=None, help="Rejection reason")
@click.option("--by", default="admin", help="Who is rejecting")
def reject_policy(policy_id, reason, by):
    """Reject a policy from promotion."""
    try:
        result = client.policy_reject(policy_id, reason=reason)
        print_success(f"Policy {policy_id} rejected")
        if reason:
            print_kv({"Reason": reason})
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@policy.command("promote")
@click.argument("policy_id")
@click.option("--by", default="admin", help="Who is promoting")
def promote_policy(policy_id, by):
    """Promote an approved policy to production."""
    try:
        result = client.policy_promote(policy_id, promoted_by=by)
        print_success(f"Policy {policy_id} promoted to production")
        print_kv(result)
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@policy.command("download")
@click.argument("policy_id")
@click.option("--output", "-o", required=True, help="Output file path (e.g. model.zip)")
def download_policy(policy_id, output):
    """Download a policy .zip file from storage."""
    try:
        data = client.policy_download(policy_id)
        if not isinstance(data, bytes):
            print_error("Unexpected response — expected binary file")
            raise SystemExit(1)
        with open(output, "wb") as f:
            f.write(data)
        print_success(f"Policy saved to {output} ({len(data):,} bytes)")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)


@policy.command("delete")
@click.argument("policy_id")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def delete_policy(policy_id, yes):
    """Delete a policy bundle record."""
    if not yes:
        click.confirm(f"Delete policy {policy_id}?", abort=True)
    try:
        client.policy_delete(policy_id)
        print_success(f"Policy {policy_id} deleted")
    except APIError as e:
        print_error(str(e))
        raise SystemExit(1)
