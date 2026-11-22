"""Run the grid: start each worker, restart it when it dies, grade the result."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from .check import grade
from .control import Control
from .spec import RunConfig

RUN_DEADLINE_S = 90.0
MAX_RESTARTS = 4
BASE_PORT = 21000


def _spawn(cfg: RunConfig, url: str, log) -> subprocess.Popen:
    env = {**os.environ, "KILLPOINT_URL": url, "KILLPOINT_CFG": cfg.to_json(), "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(
        [sys.executable, "-m", "killpoint.worker"], env=env, stdout=log, stderr=subprocess.STDOUT
    )


def run_one(cfg: RunConfig, control: Control, url: str) -> dict:
    control.register(cfg.run_id, cfg.llm_mode, cfg.crash)
    deadline = time.monotonic() + RUN_DEADLINE_S
    restarts = 0
    completed = False
    error = ""
    with tempfile.TemporaryFile() as log:
        while True:
            proc = _spawn(cfg, url, log)
            try:
                code = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                error = "deadline exceeded"
                break
            if code == 0:
                completed = control.state(cfg.run_id).done is not None
                if not completed:
                    error = "worker exited 0 without reporting a result"
                break
            if code == -9 and restarts < MAX_RESTARTS:
                # Killed at a crash point. A real deployment restarts the
                # process (systemd, Kubernetes); so do we.
                restarts += 1
                continue
            error = f"worker exited with code {code}"
            break
        if error:
            log.seek(0)
            tail = log.read().decode(errors="replace")[-1500:]
            error = f"{error}\n{tail}".strip()
    result = grade(cfg, control.state(cfg.run_id), completed, restarts, error)
    control.forget(cfg.run_id)
    return result


def run_grid(runs: list[RunConfig], out: Path, parallel: int = 4, progress: bool = True) -> list[dict]:
    from .runtimes import langgraph_rt

    if any(r.runtime.startswith("langgraph") for r in runs):
        langgraph_rt.setup()
    control = Control()
    url = control.serve()
    runs = [replace(r, port=BASE_PORT + i) if r.runtime == "restate" else r for i, r in enumerate(runs)]
    results: list[dict] = []
    started = time.monotonic()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as sink, ThreadPoolExecutor(parallel) as pool:
        futures = [pool.submit(run_one, cfg, control, url) for cfg in runs]
        for n, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            results.append(res)
            sink.write(json.dumps(res) + "\n")
            sink.flush()
            if progress and (n % 25 == 0 or n == len(runs)):
                print(f"  {n}/{len(runs)} runs, {time.monotonic() - started:.0f}s", file=sys.stderr, flush=True)
    control.shutdown()
    return results
