"""Command line: killpoint run | report."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import spec
from .report import render
from .runner import run_grid
from .spec import CrashPoint


def _csv(value: str | None, default):
    return tuple(value.split(",")) if value else default


def main() -> None:
    parser = argparse.ArgumentParser(prog="killpoint")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the grid against live runtimes")
    run.add_argument("--runtimes")
    run.add_argument("--granularities")
    run.add_argument("--llm-modes")
    run.add_argument("--keys")
    run.add_argument("--crash", help="only these crash kinds (comma separated), or 'none'")
    run.add_argument("--trials", type=int, default=1, help="repeat every run this many times")
    run.add_argument("--parallel", type=int, default=4)
    run.add_argument("--out", default="results/runs.jsonl")

    rep = sub.add_parser("report", help="render a results file as markdown")
    rep.add_argument("results", nargs="?", default="results/runs.jsonl")
    rep.add_argument("--out")

    args = parser.parse_args()
    if args.cmd == "run":
        points: list[CrashPoint | None] = [None, *spec.crash_points()]
        if args.crash:
            kinds = set(args.crash.split(","))
            points = [p for p in points if (p.kind if p else "none") in kinds]
        stamp = time.strftime("%H%M%S")
        runs = []
        for trial in range(args.trials):
            runs += spec.grid(
                _csv(args.runtimes, spec.RUNTIMES),
                _csv(args.granularities, spec.GRANULARITIES),
                _csv(args.llm_modes, spec.LLM_MODES),
                _csv(args.keys, spec.KEY_STRATEGIES),
                points,
                prefix=f"kp{stamp}x{trial}n",
            )
        print(f"{len(runs)} runs")
        results = run_grid(runs, Path(args.out), args.parallel)
        print(render(results, summary_only=True))
    else:
        results = [json.loads(line) for line in Path(args.results).read_text().splitlines() if line.strip()]
        text = render(results)
        if args.out:
            Path(args.out).write_text(text)
        else:
            print(text)


if __name__ == "__main__":
    main()
