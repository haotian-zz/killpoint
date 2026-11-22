"""Turn graded runs into markdown tables."""

from __future__ import annotations

from collections import Counter, defaultdict

from .spec import CRASH_KINDS, GRANULARITIES, KEY_STRATEGIES, LLM_MODES, RUNTIMES

BAD = ("duplicate", "lost", "diverged", "stuck", "bad_history")


def _order(values, canon):
    return [v for v in canon if v in values] + sorted(set(values) - set(canon))


def _cell(runs: list[dict]) -> str:
    """Summarise the runs behind one table cell."""
    if not runs:
        return "-"
    n = len(runs)
    counts = Counter(r["outcome"] for r in runs)
    parts = [f"{name} {counts[name]}/{n}" for name in BAD if counts[name]]
    return ", ".join(parts) if parts else f"ok {n}/{n}"


def validity(results: list[dict]) -> list[str]:
    """Problems that would make the numbers untrustworthy."""
    problems = []
    not_fired = [r for r in results if r["crash_fired"] is False]
    if not_fired:
        problems.append(f"{len(not_fired)} runs never reached their crash point")
    bad_baseline = [r for r in results if r["crash"] == "none" and r["outcome"] != "exactly_once"]
    if bad_baseline:
        problems.append(f"{len(bad_baseline)} crash-free baseline runs were not exactly-once")
    errors = [r for r in results if r["error"]]
    if errors:
        problems.append(f"{len(errors)} runs ended with a harness error or timeout")
    wrong_restarts = [r for r in results if r["crash_fired"] and r["restarts"] != 1 and not r["error"]]
    if wrong_restarts:
        problems.append(f"{len(wrong_restarts)} crashed runs did not restart exactly once")
    return problems


def render(results: list[dict], summary_only: bool = False) -> str:
    out: list[str] = []
    crashed = [r for r in results if r["crash"] != "none"]
    runtimes = _order({r["runtime"] for r in results}, RUNTIMES)
    grans = _order({r["granularity"] for r in results}, GRANULARITIES)
    keys = _order({r["key_strategy"] for r in results}, KEY_STRATEGIES)
    modes = _order({r["llm_mode"] for r in results}, LLM_MODES)
    kinds = _order({r["crash_kind"] for r in crashed}, CRASH_KINDS)

    out.append(f"Runs: {len(results)} ({len(crashed)} with a crash, {len(results) - len(crashed)} baselines).")
    problems = validity(results)
    out.append("")
    out.append("Validity checks: " + ("all passed." if not problems else "; ".join(problems) + "."))
    out.append("")

    by = defaultdict(list)
    for r in crashed:
        by[(r["runtime"], r["granularity"], r["llm_mode"], r["key_strategy"])].append(r)

    for mode in modes:
        out.append(f"### Outcome of crashed runs, {mode} model")
        out.append("")
        out.append("| runtime | step granularity | " + " | ".join(f"key: {k}" for k in keys) + " |")
        out.append("|---|---|" + "---|" * len(keys))
        for rt in runtimes:
            for gran in grans:
                cells = [_cell(by[(rt, gran, mode, k)]) for k in keys]
                out.append(f"| {rt} | {gran} | " + " | ".join(cells) + " |")
        out.append("")
    if summary_only:
        return "\n".join(out)

    out.append("### Where the crash has to land to cause damage (no idempotency key, all models)")
    out.append("")
    out.append("| runtime | step granularity | " + " | ".join(kinds) + " |")
    out.append("|---|---|" + "---|" * len(kinds))
    by_kind = defaultdict(list)
    for r in crashed:
        if r["key_strategy"] == "none":
            by_kind[(r["runtime"], r["granularity"], r["crash_kind"])].append(r)
    for rt in runtimes:
        for gran in grans:
            out.append(f"| {rt} | {gran} | " + " | ".join(_cell(by_kind[(rt, gran, k)]) for k in kinds) + " |")
    out.append("")

    out.append("### Repeated model calls per crashed run (mean extra calls)")
    out.append("")
    out.append("| runtime | " + " | ".join(grans) + " |")
    out.append("|---|" + "---|" * len(grans))
    extra = defaultdict(list)
    for r in crashed:
        extra[(r["runtime"], r["granularity"])].append(r["extra_llm_calls"])
    for rt in runtimes:
        row = []
        for gran in grans:
            vals = extra[(rt, gran)]
            row.append(f"{sum(vals) / len(vals):.2f}" if vals else "-")
        out.append(f"| {rt} | " + " | ".join(row) + " |")
    out.append("")
    return "\n".join(out)
