"""After a process kill, get_state().next is empty for a thread that is not finished.

Usage (needs a Postgres the PostgresSaver can write to):

    export PG="postgresql://postgres:killpoint@127.0.0.1:54329/killpoint_langgraph"
    python langgraph_next_repro.py

Each trial starts a child process that runs a two-node graph (a -> b) with the
default durability and SIGKILLs itself at the top of node b. The parent then
reads get_state().next, the way an application would before deciding whether
the thread needs resuming, and tallies what it saw.
"""

import os
import signal
import subprocess
import sys
import time
import uuid
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

PG = os.environ.get("PG", "postgresql://postgres:killpoint@127.0.0.1:54329/killpoint_langgraph")


class State(TypedDict, total=False):
    a_done: bool
    b_done: bool


def node_a(state: State) -> dict:
    return {"a_done": True}


def node_b(state: State) -> dict:
    if os.environ.get("DIE_IN_B"):
        time.sleep(float(os.environ.get("DELAY_MS", "2")) / 1000)
        os.kill(os.getpid(), signal.SIGKILL)
    return {"b_done": True}


def build(saver):
    g = StateGraph(State)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("b", END)
    return g.compile(checkpointer=saver)


def child(thread_id: str) -> None:
    with PostgresSaver.from_conn_string(PG) as saver:
        saver.setup()
        build(saver).invoke({}, {"configurable": {"thread_id": thread_id}})


def one_trial() -> tuple[tuple, dict]:
    thread_id = f"repro-{uuid.uuid4().hex[:8]}"
    code = subprocess.run(
        [sys.executable, __file__, "child", thread_id], env={**os.environ, "DIE_IN_B": "1"}
    ).returncode
    assert code == -signal.SIGKILL, f"child was expected to die in node b, exit code {code}"
    config = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(PG) as saver:
        graph = build(saver)
        snap = graph.get_state(config)
        # What an application sees before deciding whether the thread needs resuming.
        seen = snap.next
        result = graph.invoke(None, config)
    return seen, result


def parent(trials: int = 20) -> None:
    tally: dict[tuple, int] = {}
    for _ in range(trials):
        seen, result = one_trial()
        assert result == {"a_done": True, "b_done": True}, result
        tally[seen] = tally.get(seen, 0) + 1
    print(f"{trials} threads, each killed inside node b, so none of them finished.")
    print("get_state().next right after the kill:")
    for seen, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        note = "   <- reads as 'nothing left to run'" if seen == () else ""
        print(f"  {seen!r:16} {count:3d}{note}")
    print("invoke(None, config) completed the run in every case.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child(sys.argv[2])
    else:
        parent()
