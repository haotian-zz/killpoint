"""DBOS Transact: a workflow function whose steps are @DBOS.step functions."""

from __future__ import annotations

import os

from dbos import DBOS, DBOSConfig, SetWorkflowID

from .. import agent
from ..spec import RunConfig

SYSTEM_DB = "postgresql://postgres:killpoint@127.0.0.1:54329/killpoint_dbos"


def _native() -> str:
    return f"{DBOS.workflow_id}:{DBOS.step_id}"


@DBOS.step()
def llm_step(cfg_json: str, turn: int) -> list[dict]:
    return agent.llm_step(RunConfig.from_json(cfg_json), turn)


@DBOS.step()
def tool_step(cfg_json: str, turn: int, call: int, tool_call: dict) -> dict:
    return agent.tool_step(RunConfig.from_json(cfg_json), turn, call, tool_call, _native())


@DBOS.step()
def batch_step(cfg_json: str, turn: int, calls: list[dict]) -> list[dict]:
    return agent.batch_step(RunConfig.from_json(cfg_json), turn, calls, _native())


@DBOS.step()
def turn_step(cfg_json: str, turn: int) -> list[dict] | None:
    return agent.turn_step(RunConfig.from_json(cfg_json), turn, _native())


@DBOS.workflow()
def agent_workflow(cfg_json: str, granularity: str) -> list[dict]:
    history: list[dict] = []
    turn = 0
    while True:
        turn += 1
        if granularity == "per_turn":
            results = turn_step(cfg_json, turn)
            if results is None:
                return history
            history.extend(results)
            continue
        calls = llm_step(cfg_json, turn)
        if not calls:
            return history
        if granularity == "per_batch":
            history.extend(batch_step(cfg_json, turn, calls))
        else:
            for i, tool_call in enumerate(calls, start=1):
                history.append(tool_step(cfg_json, turn, i, tool_call))


def run(cfg: RunConfig) -> None:
    # Isolation between concurrent runs. On launch DBOS re-enqueues the pending
    # workflows of this executor id onto an internal queue, and any process with
    # the same application version may dequeue them. A per-run version keeps a
    # recovered workflow in the worker that belongs to it; with a shared version
    # another run's worker picks it up and takes it down when that worker exits.
    config: DBOSConfig = {
        "name": "killpoint",
        "system_database_url": SYSTEM_DB,
        "executor_id": cfg.run_id,
        "application_version": f"kp-{cfg.run_id}",
        "log_level": os.environ.get("KILLPOINT_DBOS_LOG", "ERROR"),
        "run_admin_server": False,
    }
    DBOS(config=config)
    DBOS.launch()
    with SetWorkflowID(cfg.run_id):
        handle = DBOS.start_workflow(agent_workflow, cfg.to_json(), cfg.granularity)
    history = handle.get_result()
    agent.report_done(cfg, history)
