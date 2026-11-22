"""Tests for the parts that do not need a runtime: ledger, crash oracle, grader."""

from killpoint import spec
from killpoint.check import grade
from killpoint.control import Control
from killpoint.spec import CrashPoint, RunConfig


def cfg(**kw) -> RunConfig:
    base = dict(run_id="t", runtime="temporal", granularity="per_call", llm_mode="deterministic", key_strategy="none")
    return RunConfig(**{**base, **kw})


def play(control: Control, key_for=lambda t, c, args: None, repeat=()) -> list[dict]:
    """Drive a full, crash-free agent loop straight against the control object.
    ``repeat`` lists (turn, call) pairs to send twice."""
    history = []
    for turn in range(1, spec.LLM_TURNS + 1):
        for i, tc in enumerate(control.llm("t", turn)["calls"], start=1):
            for _ in range(2 if (turn, i) in repeat else 1):
                out = control.effect("t", turn, i, tc["args"], key_for(turn, i, tc["args"]))
            history.append({"turn": turn, "call": i, "args": tc["args"], "receipt": out["receipt"]})
    control.done("t", {"history": history})
    return history


def test_grid_shape():
    points = spec.crash_points()
    assert len(points) == 2 * spec.LLM_TURNS + 2 * sum(spec.CALLS_PER_TURN)
    assert len({p.label for p in points}) == len(points)
    runs = spec.grid()
    assert len({r.run_id for r in runs}) == len(runs)
    cells = len(spec.RUNTIMES) * len(spec.GRANULARITIES) * len(spec.LLM_MODES) * len(spec.KEY_STRATEGIES)
    assert len(runs) == cells * (len(points) + 1)


def test_config_roundtrip():
    c = cfg(crash=CrashPoint("tool_after", 2, 1), port=5)
    assert RunConfig.from_json(c.to_json()) == c
    assert RunConfig.from_json(cfg().to_json()).crash is None


def test_clean_run_is_exactly_once():
    control = Control()
    control.register("t", "deterministic", None)
    play(control)
    result = grade(cfg(), control.state("t"), completed=True, restarts=0)
    assert result["outcome"] == "exactly_once"
    assert result["extra_effects"] == 0 and result["extra_llm_calls"] == 0


def test_repeat_without_key_is_duplicate():
    control = Control()
    control.register("t", "deterministic", None)
    play(control, repeat={(2, 1)})
    result = grade(cfg(), control.state("t"), completed=True, restarts=1)
    assert result["outcome"] == "duplicate"
    assert result["duplicated"] == ["t2c1"]
    assert result["extra_effects"] == 1


def test_repeat_with_key_is_deduplicated():
    control = Control()
    control.register("t", "deterministic", None)
    play(control, key_for=lambda t, c, a: f"k{t}{c}", repeat={(2, 1)})
    result = grade(cfg(key_strategy="position"), control.state("t"), completed=True, restarts=1)
    assert result["outcome"] == "exactly_once"
    assert result["deduped_requests"] == 1


def test_missing_effect_is_lost():
    control = Control()
    control.register("t", "deterministic", None)
    control.effect("t", 1, 1, {}, None)
    control.done("t", {"history": []})
    result = grade(cfg(), control.state("t"), completed=True, restarts=0)
    assert result["outcome"] == "lost"
    assert "t2c1" in result["lost"]


def test_unfinished_run_is_stuck():
    control = Control()
    control.register("t", "deterministic", None)
    result = grade(cfg(), control.state("t"), completed=False, restarts=0, error="deadline exceeded")
    assert result["outcome"] == "stuck"


def test_agent_record_that_disagrees_with_service_is_diverged():
    control = Control()
    control.register("t", "nondeterministic", None)
    history = play(control, key_for=lambda t, c, a: f"k{t}{c}")
    history[0]["args"] = {**history[0]["args"], "memo": "something the service never saw"}
    control.done("t", {"history": history})
    result = grade(cfg(), control.state("t"), completed=True, restarts=1)
    assert result["outcome"] == "diverged"
    assert result["diverged"] == ["t1c1"]


def test_nondeterministic_model_rephrases_on_repeat():
    control = Control()
    control.register("t", "nondeterministic", None)
    first, second = control.llm("t", 1), control.llm("t", 1)
    assert first["calls"][0]["args"]["account"] == second["calls"][0]["args"]["account"]
    assert first["calls"][0]["args"]["memo"] != second["calls"][0]["args"]["memo"]
    control.register("d", "deterministic", None)
    assert control.llm("d", 1) == control.llm("d", 1)
    assert control.llm("d", spec.LLM_TURNS)["calls"] == []


def test_crash_oracle_fires_once():
    control = Control()
    control.register("t", "deterministic", CrashPoint("tool_after", 2, 1))
    assert control.crashpoint("t", "tool_before", 2, 1) is False
    assert control.crashpoint("t", "tool_after", 2, 1) is True
    assert control.crashpoint("t", "tool_after", 2, 1) is False
    assert control.state("t").trace == ["tool_before@t2c1", "tool_after@t2c1", "tool_after@t2c1"]


def test_http_roundtrip(monkeypatch):
    control = Control()
    url = control.serve()
    control.register("t", "deterministic", None)
    from killpoint import agent

    monkeypatch.setattr(agent, "CONTROL_URL", url)
    c = cfg(key_strategy="args_hash")
    calls = agent.llm_step(c, 1)
    first = agent.tool_step(c, 1, 1, calls[0])
    again = agent.tool_step(c, 1, 1, calls[0])
    assert first["receipt"] == again["receipt"]
    assert len(control.state("t").applied) == 1
    control.shutdown()
