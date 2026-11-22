"""A finished @task can run again if the process dies right after it returns.

Usage (needs a Postgres the PostgresSaver can write to):

    export PG="postgresql://postgres:killpoint@127.0.0.1:54329/killpoint_langgraph"
    python langgraph_task_repro.py [trials]

Each trial runs an entrypoint with two tasks in sequence. Task ``charge``
appends one line to a file, which stands in for an external side effect. Task
``then_die`` SIGKILLs the process as its first statement. The parent resumes the
thread with invoke(None) and counts the lines. One line means the saved result
of ``charge`` was reused. Two lines mean ``charge`` ran a second time.

The entrypoint is invoked with durability="sync" unless DURABILITY says
otherwise. DELAY_MS makes ``then_die`` wait that long before the kill.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.func import entrypoint, task

DURABILITY = os.environ.get("DURABILITY", "sync")
PG = os.environ.get("PG", "postgresql://postgres:killpoint@127.0.0.1:54329/killpoint_langgraph")


@task
def charge(effects_file: str) -> str:
    with open(effects_file, "a") as f:
        f.write("charged\n")
        f.flush()
        os.fsync(f.fileno())
    return "receipt"


@task
def then_die() -> str:
    if os.environ.get("DIE"):
        time.sleep(float(os.environ.get("DELAY_MS", "0")) / 1000)
        os.kill(os.getpid(), signal.SIGKILL)
    return "survived"


def build(saver):
    @entrypoint(checkpointer=saver)
    def flow(effects_file: str) -> dict:
        receipt = charge(effects_file).result()
        return {"receipt": receipt, "second": then_die().result()}

    return flow


def child(thread_id: str, effects_file: str) -> None:
    with PostgresSaver.from_conn_string(PG) as saver:
        saver.setup()
        build(saver).invoke(effects_file, {"configurable": {"thread_id": thread_id}}, durability=DURABILITY)


def one_trial(workdir: str) -> int:
    thread_id = f"task-repro-{uuid.uuid4().hex[:8]}"
    effects_file = os.path.join(workdir, thread_id)
    code = subprocess.run(
        [sys.executable, __file__, "child", thread_id, effects_file], env={**os.environ, "DIE": "1"}
    ).returncode
    assert code == -signal.SIGKILL, f"child was expected to die in then_die, exit code {code}"
    with PostgresSaver.from_conn_string(PG) as saver:
        result = build(saver).invoke(None, {"configurable": {"thread_id": thread_id}}, durability=DURABILITY)
    assert result == {"receipt": "receipt", "second": "survived"}, result
    with open(effects_file) as f:
        return len(f.readlines())


def parent(trials: int) -> None:
    with tempfile.TemporaryDirectory() as workdir:
        counts = [one_trial(workdir) for _ in range(trials)]
    twice = sum(1 for n in counts if n == 2)
    print(f"durability={DURABILITY} delay={os.environ.get('DELAY_MS', '0')}ms: {trials} trials. charge ran once in {counts.count(1)}, twice in {twice}.")
    assert set(counts) <= {1, 2}, counts


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child(sys.argv[2], sys.argv[3])
    else:
        parent(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
