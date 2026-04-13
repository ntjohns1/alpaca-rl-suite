"""
Temporal workflows for Alpaca RL Suite.

Workflows:
  - TrainingWorkflow   : kick off rl-train, poll until done, run backtest, promote if Sharpe > threshold
  - BacktestWorkflow   : run backtest for an existing policy, store result
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# ─────────────────────────────────────────
# Activity stubs (imported from activities.py)
# ─────────────────────────────────────────
with workflow.unsafe.imports_passed_through():
    from activities import (
        start_training_run,
        poll_training_run,
        run_backtest,
        promote_policy,
        notify_slack,
    )


# ─────────────────────────────────────────
# Training Workflow
# ─────────────────────────────────────────
@workflow.defn
class TrainingWorkflow:
    """
    1. Start a training run via rl-train HTTP API.
    2. Poll until the run completes (or fails / times out).
    3. Run a backtest against the trained policy.
    4. If Sharpe ≥ threshold, promote the policy to 'promoted' status.
    5. Notify on completion or failure.
    """

    @workflow.run
    async def run(self, params: dict) -> dict:
        retry = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))

        # Step 1: kick off training
        run_id: str = await workflow.execute_activity(
            start_training_run,
            params,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry,
        )
        workflow.logger.info(f"Training run started: {run_id}")

        # Step 2: poll until done (max 6 hours)
        result: dict = await workflow.execute_activity(
            poll_training_run,
            {"run_id": run_id, "timeout_s": 21600},
            start_to_close_timeout=timedelta(hours=7),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if result.get("status") != "completed":
            await workflow.execute_activity(
                notify_slack,
                {"message": f"Training run {run_id} FAILED: {result.get('error')}"},
                start_to_close_timeout=timedelta(seconds=10),
            )
            return {"status": "failed", "run_id": run_id, **result}

        workflow.logger.info(f"Training complete: {result}")

        # Step 3: backtest
        backtest_result: dict = await workflow.execute_activity(
            run_backtest,
            {
                "policy_s3_path": result["artifact_path"],
                "symbols": params.get("symbols", ["AAPL"]),
                "start_date": params.get("backtest_start", "2023-01-01"),
                "end_date": params.get("backtest_end", "2023-12-31"),
            },
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=retry,
        )
        workflow.logger.info(f"Backtest result: {backtest_result}")

        # Step 4: promote if Sharpe ≥ threshold
        sharpe_threshold = params.get("sharpe_threshold", 0.5)
        promoted = False
        if backtest_result.get("sharpeRatio", 0) >= sharpe_threshold:
            await workflow.execute_activity(
                promote_policy,
                {"run_id": run_id, "artifact_path": result["artifact_path"]},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            promoted = True
            workflow.logger.info(f"Policy promoted for run {run_id}")

        # Step 5: notify
        msg = (
            f"Training {run_id} complete. "
            f"Sharpe={backtest_result.get('sharpeRatio', 'N/A')}, "
            f"promoted={promoted}"
        )
        await workflow.execute_activity(
            notify_slack,
            {"message": msg},
            start_to_close_timeout=timedelta(seconds=10),
        )

        return {
            "status": "completed",
            "run_id": run_id,
            "promoted": promoted,
            "training": result,
            "backtest": backtest_result,
        }


# ─────────────────────────────────────────
# Backtest Workflow
# ─────────────────────────────────────────
@workflow.defn
class BacktestWorkflow:
    """
    Run a standalone backtest for an existing policy S3 path.
    """

    @workflow.run
    async def run(self, params: dict) -> dict:
        retry = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))

        result: dict = await workflow.execute_activity(
            run_backtest,
            params,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=retry,
        )
        workflow.logger.info(f"Backtest complete: {result}")
        return result
