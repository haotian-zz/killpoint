"""Temporal: a workflow whose steps are activities."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from .. import agent
    from ..spec import RunConfig

ADDRESS = "127.0.0.1:17233"

# A killed worker never reports failure, so the server learns about it only when
# the activity's start-to-close timeout expires. Steps here take milliseconds; the
# timeout is short to keep runs fast and long enough that a healthy step never hits it.
STEP_TIMEOUT = timedelta(seconds=5)
RETRY = RetryPolicy(initial_interval=timedelta(milliseconds=200))


def _native() -> str:
    info = activity.info()
    return f"{info.workflow_id}:{info.activity_id}"


@activity.defn
def llm_activity(cfg_json: str, turn: int) -> list[dict]:
    return agent.llm_step(RunConfig.from_json(cfg_json), turn)


@activity.defn
def tool_activity(cfg_json: str, turn: int, call: int, tool_call: dict) -> dict:
    return agent.tool_step(RunConfig.from_json(cfg_json), turn, call, tool_call, _native())


@activity.defn
def batch_activity(cfg_json: str, turn: int, calls: list[dict]) -> list[dict]:
    return agent.batch_step(RunConfig.from_json(cfg_json), turn, calls, _native())


@activity.defn
def turn_activity(cfg_json: str, turn: int) -> list[dict] | None:
    return agent.turn_step(RunConfig.from_json(cfg_json), turn, _native())


@workflow.defn
class AgentWorkflow:
    @workflow.run
    async def run(self, cfg_json: str, granularity: str) -> list[dict]:
        opts = dict(start_to_close_timeout=STEP_TIMEOUT, retry_policy=RETRY)
        history: list[dict] = []
        turn = 0
        while True:
            turn += 1
            if granularity == "per_turn":
                results = await workflow.execute_activity(turn_activity, args=[cfg_json, turn], **opts)
                if results is None:
                    return history
                history.extend(results)
                continue
            calls = await workflow.execute_activity(llm_activity, args=[cfg_json, turn], **opts)
            if not calls:
                return history
            if granularity == "per_batch":
                history.extend(await workflow.execute_activity(batch_activity, args=[cfg_json, turn, calls], **opts))
            else:
                for i, tool_call in enumerate(calls, start=1):
                    history.append(
                        await workflow.execute_activity(tool_activity, args=[cfg_json, turn, i, tool_call], **opts)
                    )


async def _main(cfg: RunConfig) -> None:
    client = await Client.connect(ADDRESS)
    # One task queue per run, so killing this worker cannot touch another run.
    queue = f"kp-{cfg.run_id}"
    worker = Worker(
        client,
        task_queue=queue,
        workflows=[AgentWorkflow],
        activities=[llm_activity, tool_activity, batch_activity, turn_activity],
        activity_executor=ThreadPoolExecutor(4),
        sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
    )
    async with worker:
        try:
            handle = await client.start_workflow(
                AgentWorkflow.run,
                args=[cfg.to_json(), cfg.granularity],
                id=cfg.run_id,
                task_queue=queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(cfg.run_id)
        history = await handle.result()
    agent.report_done(cfg, history)


def run(cfg: RunConfig) -> None:
    asyncio.run(_main(cfg))
