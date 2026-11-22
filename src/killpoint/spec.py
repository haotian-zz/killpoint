"""The workload and the experiment grid.

The workload is a fixed tool-calling agent loop. On each turn the agent asks the
model what to do, then executes the tool calls it got back. The scripted model
returns ``CALLS_PER_TURN[turn]`` calls and an empty list once the script runs out,
which ends the loop. Every tool call has an external side effect.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from itertools import product

# Tool calls the scripted model asks for on turns 1..3. Turn 4 returns no calls.
CALLS_PER_TURN = (1, 2, 1)
LLM_TURNS = len(CALLS_PER_TURN) + 1

# langgraph runs with its default durability ("async": checkpoints are written
# in the background while the next step runs); langgraph_sync writes each
# checkpoint before the next step starts.
RUNTIMES = ("temporal", "dbos", "restate", "langgraph", "langgraph_sync")

# How much work sits inside one durable step.
#   per_call  : the model call and every tool call are separate steps
#   per_batch : the model call is a step; all tool calls of a turn share one step
#   per_turn  : the model call and its tool calls share one step
GRANULARITIES = ("per_call", "per_batch", "per_turn")

# Whether the model returns the same arguments when asked the same thing twice.
LLM_MODES = ("deterministic", "nondeterministic")

# How the idempotency key sent with a tool call is built.
#   none      : no key
#   args_hash : hash of the tool name and arguments
#   position  : run id + turn + call index, known before the model is asked
#   native    : an identifier the runtime itself gives the step
KEY_STRATEGIES = ("none", "args_hash", "position", "native")

CRASH_KINDS = ("llm_before", "llm_after", "tool_before", "tool_after")


@dataclass(frozen=True)
class CrashPoint:
    """Where the worker is killed. ``call`` is 0 for model-call points."""

    kind: str
    turn: int
    call: int = 0

    @property
    def label(self) -> str:
        if self.kind.startswith("llm"):
            return f"{self.kind}@t{self.turn}"
        return f"{self.kind}@t{self.turn}c{self.call}"


def tool_intents() -> list[tuple[int, int]]:
    """Every (turn, call) the agent is supposed to execute exactly once."""
    return [(t, c) for t, n in enumerate(CALLS_PER_TURN, start=1) for c in range(1, n + 1)]


def crash_points() -> list[CrashPoint]:
    points = []
    for turn in range(1, LLM_TURNS + 1):
        points.append(CrashPoint("llm_before", turn))
        points.append(CrashPoint("llm_after", turn))
        for call in range(1, (CALLS_PER_TURN[turn - 1] if turn <= len(CALLS_PER_TURN) else 0) + 1):
            points.append(CrashPoint("tool_before", turn, call))
            points.append(CrashPoint("tool_after", turn, call))
    return points


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    runtime: str
    granularity: str
    llm_mode: str
    key_strategy: str
    crash: CrashPoint | None = None
    port: int = 0  # only used by runtimes whose worker has to listen (restate)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(raw: str) -> "RunConfig":
        data = json.loads(raw)
        crash = data.pop("crash")
        return RunConfig(**data, crash=CrashPoint(**crash) if crash else None)

    @property
    def cell(self) -> tuple[str, str, str, str]:
        return (self.runtime, self.granularity, self.llm_mode, self.key_strategy)


def grid(
    runtimes=RUNTIMES,
    granularities=GRANULARITIES,
    llm_modes=LLM_MODES,
    key_strategies=KEY_STRATEGIES,
    points: list[CrashPoint | None] | None = None,
    prefix: str = "r",
) -> list[RunConfig]:
    """One run per cell per crash point, plus a crash-free baseline per cell."""
    if points is None:
        points = [None, *crash_points()]
    runs = []
    for n, (rt, gran, mode, key, point) in enumerate(
        product(runtimes, granularities, llm_modes, key_strategies, points)
    ):
        runs.append(RunConfig(f"{prefix}{n:05d}", rt, gran, mode, key, point))
    return runs
