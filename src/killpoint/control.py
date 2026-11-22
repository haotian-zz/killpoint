"""Control plane: scripted model, effect ledger and crash oracle in one HTTP server.

It lives in the harness process, outside every runtime under test, so what it
records is independent of what a runtime's own journal or checkpoint says.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .spec import CALLS_PER_TURN, CrashPoint


@dataclass
class RunState:
    llm_mode: str = "deterministic"
    crash: CrashPoint | None = None
    crash_fired: bool = False
    llm_calls: dict[int, int] = field(default_factory=dict)  # turn -> times asked
    requests: list[dict] = field(default_factory=list)  # every tool request received
    applied: dict[str, dict] = field(default_factory=dict)  # dedupe key -> applied effect
    trace: list[str] = field(default_factory=list)  # crash points reached, in order
    done: dict | None = None


class Control:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunState] = {}
        self._server: ThreadingHTTPServer | None = None

    # -- harness side ------------------------------------------------------

    def register(self, run_id: str, llm_mode: str, crash: CrashPoint | None) -> None:
        with self._lock:
            self._runs[run_id] = RunState(llm_mode=llm_mode, crash=crash)

    def state(self, run_id: str) -> RunState:
        with self._lock:
            return self._runs[run_id]

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)

    # -- worker side (also callable directly, which the unit tests do) ------

    def llm(self, run_id: str, turn: int) -> dict:
        """Scripted model. In nondeterministic mode a repeated question gets the
        same tool calls with different free-text arguments, the way a real model
        rephrases itself."""
        with self._lock:
            run = self._runs[run_id]
            attempt = run.llm_calls.get(turn, 0) + 1
            run.llm_calls[turn] = attempt
            mode = run.llm_mode
        n_calls = CALLS_PER_TURN[turn - 1] if turn <= len(CALLS_PER_TURN) else 0
        calls = []
        for call in range(1, n_calls + 1):
            memo = "charge" if mode == "deterministic" else f"charge (phrasing {attempt})"
            calls.append(
                {
                    "tool": "charge",
                    "args": {"account": f"acct-{turn}-{call}", "amount": 100 * turn + call, "memo": memo},
                }
            )
        return {"calls": calls}

    def effect(self, run_id: str, turn: int, call: int, args: dict, key: str | None) -> dict:
        """The external service. A request without a key always takes effect. A
        request with a key takes effect only the first time that key is seen."""
        with self._lock:
            run = self._runs[run_id]
            seq = len(run.requests) + 1
            dedupe = key if key is not None else f"__nokey__{seq}"
            first = dedupe not in run.applied
            if first:
                run.applied[dedupe] = {"seq": seq, "turn": turn, "call": call, "args": args}
            receipt = run.applied[dedupe]["seq"]
            run.requests.append(
                {"seq": seq, "turn": turn, "call": call, "args": args, "key": key, "applied": first}
            )
        return {"receipt": receipt, "applied": first}

    def crashpoint(self, run_id: str, kind: str, turn: int, call: int) -> bool:
        """True exactly once, the first time the run reaches its crash point."""
        here = CrashPoint(kind, turn, call)
        with self._lock:
            run = self._runs[run_id]
            run.trace.append(here.label)
            if run.crash == here and not run.crash_fired:
                run.crash_fired = True
                return True
        return False

    def done(self, run_id: str, payload: dict) -> None:
        with self._lock:
            self._runs[run_id].done = payload

    # -- HTTP --------------------------------------------------------------

    def serve(self, port: int = 0) -> str:
        control = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:  # keep the harness output quiet
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
                try:
                    if self.path == "/llm":
                        out = control.llm(body["run"], body["turn"])
                    elif self.path == "/effect":
                        out = control.effect(body["run"], body["turn"], body["call"], body["args"], body.get("key"))
                    elif self.path == "/crashpoint":
                        out = {"die": control.crashpoint(body["run"], body["kind"], body["turn"], body["call"])}
                    elif self.path == "/done":
                        control.done(body["run"], body["payload"])
                        out = {}
                    else:
                        self.send_error(404)
                        return
                except KeyError as exc:
                    self.send_error(400, f"unknown run or missing field: {exc}")
                    return
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 256

        self._server = Server(("127.0.0.1", port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def shutdown(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
