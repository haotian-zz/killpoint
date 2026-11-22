"""LangGraph with the Postgres checkpointer.

per_batch and per_turn use the graph API (a model node and a tools node, or one
node for both). per_call uses the functional API, where each tool call is a
@task whose result is saved on its own.

LangGraph has no server that restarts a dead run. After a crash the application
has to notice the unfinished thread and invoke it again, which is what ``run``
does when it finds a checkpoint with pending work.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.config import get_config
from langgraph.func import entrypoint, task
from langgraph.graph import END, START, StateGraph

from .. import agent
from ..spec import RunConfig

DB = "postgresql://postgres:killpoint@127.0.0.1:54329/killpoint_langgraph"


class State(TypedDict, total=False):
    cfg: str
    turn: int
    calls: list[dict]
    done: bool
    history: Annotated[list[dict], operator.add]


def _native() -> str:
    return str(get_config()["configurable"]["__pregel_task_id"])


def _llm_node(state: State) -> dict:
    turn = state.get("turn", 0) + 1
    calls = agent.llm_step(RunConfig.from_json(state["cfg"]), turn)
    return {"turn": turn, "calls": calls, "done": not calls}


def _tools_node(state: State) -> dict:
    cfg = RunConfig.from_json(state["cfg"])
    return {"history": agent.batch_step(cfg, state["turn"], state["calls"], _native())}


def _turn_node(state: State) -> dict:
    turn = state.get("turn", 0) + 1
    results = agent.turn_step(RunConfig.from_json(state["cfg"]), turn, _native())
    if results is None:
        return {"turn": turn, "done": True}
    return {"turn": turn, "history": results}


def _batch_graph(saver):
    g = StateGraph(State)
    g.add_node("llm", _llm_node)
    g.add_node("tools", _tools_node)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", lambda s: END if s["done"] else "tools")
    g.add_edge("tools", "llm")
    return g.compile(checkpointer=saver)


def _turn_graph(saver):
    g = StateGraph(State)
    g.add_node("turn", _turn_node)
    g.add_edge(START, "turn")
    g.add_conditional_edges("turn", lambda s: END if s.get("done") else "turn")
    return g.compile(checkpointer=saver)


@task
def _llm_task(cfg_json: str, turn: int) -> list[dict]:
    return agent.llm_step(RunConfig.from_json(cfg_json), turn)


@task
def _tool_task(cfg_json: str, turn: int, call: int, tool_call: dict) -> dict:
    return agent.tool_step(RunConfig.from_json(cfg_json), turn, call, tool_call, _native())


def _call_entrypoint(saver):
    @entrypoint(checkpointer=saver)
    def agent_loop(cfg_json: str) -> dict:
        history: list[dict] = []
        turn = 0
        while True:
            turn += 1
            calls = _llm_task(cfg_json, turn).result()
            if not calls:
                return {"history": history}
            for i, tool_call in enumerate(calls, start=1):
                history.append(_tool_task(cfg_json, turn, i, tool_call).result())

    return agent_loop


def setup() -> None:
    with PostgresSaver.from_conn_string(DB) as saver:
        saver.setup()


def run(cfg: RunConfig) -> None:
    durability = "sync" if cfg.runtime == "langgraph_sync" else "async"
    config = {"configurable": {"thread_id": cfg.run_id}}
    with PostgresSaver.from_conn_string(DB) as saver:
        if cfg.granularity == "per_call":
            graph, first_input = _call_entrypoint(saver), cfg.to_json()
        elif cfg.granularity == "per_batch":
            graph, first_input = _batch_graph(saver), {"cfg": cfg.to_json()}
        else:
            graph, first_input = _turn_graph(saver), {"cfg": cfg.to_json()}

        if graph.get_state(config).created_at is None:
            # No checkpoint was ever written for this thread: start from scratch.
            result = graph.invoke(first_input, config, durability=durability)
        else:
            # Resume from the last checkpoint. Invoking with None is the reliable
            # way to do it: after a kill, get_state().next can be empty for a
            # thread that still has work to do (see findings/langgraph-next.md).
            result = graph.invoke(None, config, durability=durability)
    agent.report_done(cfg, (result or {}).get("history", []))
