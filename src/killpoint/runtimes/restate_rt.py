"""Restate: a service handler whose steps are ctx.run blocks."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

import hypercorn.asyncio
import hypercorn.config
import restate

from .. import agent
from ..spec import RunConfig

INGRESS = "http://127.0.0.1:18080"
ADMIN = "http://127.0.0.1:19070"
# The Restate server runs in a container and calls back into this host process.
CALLBACK_HOST = "host.docker.internal"


def _http(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 120):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def _service(cfg: RunConfig) -> restate.Service:
    # One service per run, served by this run's worker only, so killing the
    # worker cannot touch another run.
    svc = restate.Service(f"Agent_{cfg.run_id}")

    @svc.handler()
    async def run(ctx: restate.Context, granularity: str) -> list[dict]:
        history: list[dict] = []
        turn = 0
        while True:
            turn += 1
            # ctx.uuid() is seeded by the invocation id, so a retried attempt
            # that replays the journal gets the same value at the same position.
            native = str(ctx.uuid())
            if granularity == "per_turn":
                results = await ctx.run_typed(f"turn-{turn}", agent.turn_step, cfg=cfg, turn=turn, native=native)
                if results is None:
                    return history
                history.extend(results)
                continue
            calls = await ctx.run_typed(f"llm-{turn}", agent.llm_step, cfg=cfg, turn=turn)
            if not calls:
                return history
            if granularity == "per_batch":
                history.extend(
                    await ctx.run_typed(
                        f"tools-{turn}", agent.batch_step, cfg=cfg, turn=turn, calls=calls, native=native
                    )
                )
            else:
                for i, tool_call in enumerate(calls, start=1):
                    step_native = str(ctx.uuid())
                    history.append(
                        await ctx.run_typed(
                            f"tool-{turn}-{i}",
                            agent.tool_step,
                            cfg=cfg,
                            turn=turn,
                            call=i,
                            tool_call=tool_call,
                            native=step_native,
                        )
                    )

    return svc


def _registered(name: str) -> bool:
    try:
        _http("GET", f"{ADMIN}/services/{name}")
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


async def _main(cfg: RunConfig) -> None:
    svc = _service(cfg)
    conf = hypercorn.config.Config()
    conf.bind = [f"0.0.0.0:{cfg.port}"]
    conf.loglevel = "ERROR"
    server = asyncio.create_task(hypercorn.asyncio.serve(restate.app([svc]), conf))
    await asyncio.sleep(0.3)

    name = f"Agent_{cfg.run_id}"
    loop = asyncio.get_running_loop()
    deployment = None
    if not await loop.run_in_executor(None, _registered, name):
        deployment = await loop.run_in_executor(
            None, lambda: _http("POST", f"{ADMIN}/deployments", {"uri": f"http://{CALLBACK_HOST}:{cfg.port}"})
        )
    # The idempotency key makes a second send after a restart attach to the
    # invocation that is already running instead of starting another one.
    sent = await loop.run_in_executor(
        None,
        lambda: _http("POST", f"{INGRESS}/{name}/run/send", cfg.granularity, {"idempotency-key": cfg.run_id}),
    )
    history = await loop.run_in_executor(
        None, lambda: _http("GET", f"{INGRESS}/restate/invocation/{sent['invocationId']}/attach")
    )
    agent.report_done(cfg, history)
    # Drop the per-run deployment so the server does not accumulate thousands.
    try:
        if deployment is None:
            svc_info = await loop.run_in_executor(None, lambda: _http("GET", f"{ADMIN}/services/{name}"))
            dep_id = svc_info.get("deployment_id")
        else:
            dep_id = deployment.get("id")
        if dep_id:
            await loop.run_in_executor(None, lambda: _http("DELETE", f"{ADMIN}/deployments/{dep_id}?force=true"))
    except Exception:
        pass
    server.cancel()


def run(cfg: RunConfig) -> None:
    asyncio.run(_main(cfg))
