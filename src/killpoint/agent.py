"""The agent's step bodies, shared by every runtime adapter.

An adapter decides only how these functions are wrapped into durable steps. The
code that talks to the model and to the external service is identical everywhere,
so differences in the results come from the runtime and the wrapping.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import time
import urllib.request

from .spec import RunConfig

CONTROL_URL = os.environ.get("KILLPOINT_URL", "")


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        CONTROL_URL + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def crashpoint(cfg: RunConfig, kind: str, turn: int, call: int = 0) -> None:
    """Ask the harness whether to die here. Death is SIGKILL: no handlers, no
    finally blocks, no flushing, which is what an OOM kill or a node loss looks like."""
    if _post("/crashpoint", {"run": cfg.run_id, "kind": kind, "turn": turn, "call": call})["die"]:
        os.kill(os.getpid(), signal.SIGKILL)
        # A process-directed signal can be picked up by another thread, which
        # leaves this one running for a moment. Park it so nothing after the
        # crash point can execute.
        while True:
            time.sleep(60)


def idempotency_key(cfg: RunConfig, turn: int, call: int, tool_call: dict, native: str | None) -> str | None:
    if cfg.key_strategy == "none":
        return None
    if cfg.key_strategy == "args_hash":
        blob = json.dumps([tool_call["tool"], tool_call["args"]], sort_keys=True)
        return "args:" + hashlib.sha256(blob.encode()).hexdigest()[:16]
    if cfg.key_strategy == "position":
        return f"pos:{cfg.run_id}:{turn}:{call}"
    if cfg.key_strategy == "native":
        if native is None:
            raise RuntimeError(f"{cfg.runtime} adapter gave no native step id")
        return f"native:{native}:{call}"
    raise ValueError(cfg.key_strategy)


def llm_step(cfg: RunConfig, turn: int) -> list[dict]:
    """Ask the model for this turn's tool calls."""
    crashpoint(cfg, "llm_before", turn)
    calls = _post("/llm", {"run": cfg.run_id, "turn": turn})["calls"]
    crashpoint(cfg, "llm_after", turn)
    return calls


def tool_step(cfg: RunConfig, turn: int, call: int, tool_call: dict, native: str | None = None) -> dict:
    """Execute one tool call against the external service."""
    crashpoint(cfg, "tool_before", turn, call)
    key = idempotency_key(cfg, turn, call, tool_call, native)
    out = _post(
        "/effect",
        {"run": cfg.run_id, "turn": turn, "call": call, "args": tool_call["args"], "key": key},
    )
    crashpoint(cfg, "tool_after", turn, call)
    return {"turn": turn, "call": call, "args": tool_call["args"], "receipt": out["receipt"]}


def batch_step(cfg: RunConfig, turn: int, calls: list[dict], native: str | None = None) -> list[dict]:
    """Execute all tool calls of a turn inside one durable step."""
    return [tool_step(cfg, turn, i, tc, native) for i, tc in enumerate(calls, start=1)]


def turn_step(cfg: RunConfig, turn: int, native: str | None = None) -> list[dict] | None:
    """Ask the model and execute its tool calls inside one durable step. Returns
    None when the model had nothing more to do."""
    calls = llm_step(cfg, turn)
    if not calls:
        return None
    return batch_step(cfg, turn, calls, native)


def report_done(cfg: RunConfig, history: list[dict], note: str = "") -> None:
    _post("/done", {"run": cfg.run_id, "payload": {"history": history, "note": note}})
