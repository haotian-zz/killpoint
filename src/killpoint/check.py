"""Grade one run by comparing the ledger with what the agent was meant to do."""

from __future__ import annotations

from .control import RunState
from .spec import LLM_TURNS, RunConfig, tool_intents


def grade(cfg: RunConfig, state: RunState, completed: bool, restarts: int, error: str = "") -> dict:
    applied_per_intent = {intent: 0 for intent in tool_intents()}
    unexpected = 0
    for effect in state.applied.values():
        intent = (effect["turn"], effect["call"])
        if intent in applied_per_intent:
            applied_per_intent[intent] += 1
        else:
            unexpected += 1

    duplicated = sorted(i for i, n in applied_per_intent.items() if n > 1)
    lost = sorted(i for i, n in applied_per_intent.items() if n == 0)
    extra_effects = sum(n - 1 for n in applied_per_intent.values() if n > 1) + unexpected

    # Requests the service received and refused because their key was already used.
    deduped = sum(1 for r in state.requests if not r["applied"])

    extra_llm = sum(max(0, state.llm_calls.get(t, 0) - 1) for t in range(1, LLM_TURNS + 1))

    # Does the agent's own record match what the service actually did? It can
    # differ when a step is retried with new arguments under an old key: the
    # service keeps the first effect, the agent remembers the second request.
    history = (state.done or {}).get("history", []) if completed else []
    by_seq = {e["seq"]: e for e in state.applied.values()}
    diverged = []
    for entry in history:
        effect = by_seq.get(entry["receipt"])
        if effect is None or effect["args"] != entry["args"]:
            diverged.append((entry["turn"], entry["call"]))
    history_intents = sorted((e["turn"], e["call"]) for e in history)
    history_ok = completed and history_intents == sorted(tool_intents())

    crash_fired = state.crash_fired if cfg.crash else None

    if not completed:
        outcome = "stuck"
    elif duplicated:
        outcome = "duplicate"
    elif lost:
        outcome = "lost"
    elif diverged:
        outcome = "diverged"
    elif not history_ok:
        outcome = "bad_history"
    else:
        outcome = "exactly_once"

    return {
        "run_id": cfg.run_id,
        "runtime": cfg.runtime,
        "granularity": cfg.granularity,
        "llm_mode": cfg.llm_mode,
        "key_strategy": cfg.key_strategy,
        "crash": cfg.crash.label if cfg.crash else "none",
        "crash_kind": cfg.crash.kind if cfg.crash else "none",
        "crash_fired": crash_fired,
        "outcome": outcome,
        "completed": completed,
        "restarts": restarts,
        "duplicated": [f"t{t}c{c}" for t, c in duplicated],
        "lost": [f"t{t}c{c}" for t, c in lost],
        "diverged": [f"t{t}c{c}" for t, c in diverged],
        "extra_effects": extra_effects,
        "deduped_requests": deduped,
        "extra_llm_calls": extra_llm,
        "requests": len(state.requests),
        "trace": list(state.trace),
        "error": error,
    }
