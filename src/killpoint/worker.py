"""Worker entry point: run (or resume) one agent run on one runtime, then exit.

The harness starts this as a subprocess and starts it again whenever it dies.
"""

from __future__ import annotations

import os

from .spec import RunConfig


def main() -> None:
    cfg = RunConfig.from_json(os.environ["KILLPOINT_CFG"])
    if cfg.runtime == "temporal":
        from .runtimes import temporal_rt as rt
    elif cfg.runtime == "dbos":
        from .runtimes import dbos_rt as rt
    elif cfg.runtime == "restate":
        from .runtimes import restate_rt as rt
    elif cfg.runtime in ("langgraph", "langgraph_sync"):
        from .runtimes import langgraph_rt as rt
    else:
        raise SystemExit(f"unknown runtime {cfg.runtime}")
    rt.run(cfg)


if __name__ == "__main__":
    main()
