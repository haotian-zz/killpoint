"""A write-ahead intent log for side-effecting tool calls.

Before a tool call is sent, its intent (which call it is, and with what
arguments) is committed to a table. A retry of the same call finds the intent
and reuses its key and its arguments, so the external service sees one request
repeated and the agent's record matches what the service applied, even when the
model produced different arguments on the retry. A call whose result was
already recorded is not sent again at all.

The identity of a call is (run id, turn, call index): values that are fixed
before the model is asked.

This needs an external service that honors idempotency keys. For a service that
does not, the log still tells a retry that an earlier attempt may have taken
effect, and ``guarded`` can ask the service through ``lookup`` before sending.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_intents (
    run_id   text    NOT NULL,
    turn     integer NOT NULL,
    call     integer NOT NULL,
    tool     text    NOT NULL,
    args     jsonb   NOT NULL,
    result   jsonb,
    PRIMARY KEY (run_id, turn, call)
)
"""


@dataclass(frozen=True)
class Intent:
    key: str
    tool: str
    args: dict
    result: dict | None
    first_attempt: bool


class IntentLog:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def setup(self) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(SCHEMA)

    def begin(self, run_id: str, turn: int, call: int, tool: str, args: dict) -> Intent:
        """Record the intent, or return the one an earlier attempt recorded.
        The first attempt's arguments win."""
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            inserted = conn.execute(
                "INSERT INTO tool_intents (run_id, turn, call, tool, args) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING 1",
                (run_id, turn, call, tool, json.dumps(args)),
            ).fetchone()
            row = conn.execute(
                "SELECT tool, args, result FROM tool_intents WHERE run_id = %s AND turn = %s AND call = %s",
                (run_id, turn, call),
            ).fetchone()
        return Intent(f"intent:{run_id}:{turn}:{call}", row[0], row[1], row[2], inserted is not None)

    def complete(self, run_id: str, turn: int, call: int, result: dict) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "UPDATE tool_intents SET result = %s WHERE run_id = %s AND turn = %s AND call = %s AND result IS NULL",
                (json.dumps(result), run_id, turn, call),
            )

    def guarded(
        self,
        run_id: str,
        turn: int,
        call: int,
        tool: str,
        args: dict,
        send: Callable[[str, dict], dict],
        lookup: Callable[[str], dict | None] | None = None,
    ) -> tuple[dict, dict]:
        """Run ``send(key, args)`` at most once in effect. Returns the arguments
        that were (or had been) sent and the result.

        ``lookup(key)`` is for services without idempotency keys: on a retry it
        is asked whether the earlier attempt took effect, and its answer is used
        in place of sending again.
        """
        intent = self.begin(run_id, turn, call, tool, args)
        if intent.result is not None:
            return intent.args, intent.result
        result = None
        if not intent.first_attempt and lookup is not None:
            result = lookup(intent.key)
        if result is None:
            result = send(intent.key, intent.args)
        self.complete(run_id, turn, call, result)
        return intent.args, result
