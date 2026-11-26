"""Pure scheduler rules, without LangGraph execution."""

from __future__ import annotations

from langgraph.types import Send

from skillagent.core.types import PlanStep, RoutingDecision, SkillResult
from skillagent.graph.scheduler import (
    COMPOSER,
    dispatch,
    plan_wave,
    propagate_skips,
    ready_steps,
    skill_node_name,
)


def decision(*steps: tuple[str, str, str]) -> RoutingDecision:
    return RoutingDecision(
        response_language="en",
        steps=[PlanStep(id=i, skill=s, instruction=f"do {i}", input_from=f) for i, s, f in steps],
    )


def res(sid: str, status: str = "ok", output: str = "out") -> SkillResult:
    return SkillResult(step_id=sid, skill="x", status=status, output=output)  # type: ignore[arg-type]


CHAIN = decision(("s1", "a", "user"), ("s2", "b", "s1"), ("s3", "c", "s2"))
PARALLEL = decision(("s1", "a", "user"), ("s2", "b", "user"), ("s3", "c", "user"))


def wave(d: RoutingDecision, results: dict, **kw):
    args = {"waves_done": 0, "max_waves": 5, "max_parallel": 2, "time_left_s": 10.0} | kw
    return plan_wave(d, results, **args)


def test_ready_requires_ok_dependency() -> None:
    assert [s.id for s in ready_steps(CHAIN, {})] == ["s1"]
    assert [s.id for s in ready_steps(CHAIN, {"s1": res("s1")})] == ["s2"]
    assert ready_steps(CHAIN, {"s1": res("s1", "rejected")}) == []


def test_skips_cascade_down_a_chain_in_one_pass() -> None:
    skipped = propagate_skips(CHAIN, {"s1": res("s1", "error")})
    assert set(skipped) == {"s2", "s3"}
    assert all(r.status == "skipped" and r.meta["reason"] == "dependency" for r in skipped.values())
    assert "'error'" in (skipped["s2"].error or "")


def test_parallel_cap_spills_into_next_wave() -> None:
    first = wave(PARALLEL, {})
    assert [s.id for s in first.steps] == ["s1", "s2"]
    second = wave(PARALLEL, {"s1": res("s1"), "s2": res("s2")}, waves_done=1)
    assert [s.id for s in second.steps] == ["s3"]


def test_wave_cap_skips_everything_pending() -> None:
    result = wave(CHAIN, {"s1": res("s1")}, waves_done=1, max_waves=1)
    assert result.steps == []
    assert {k: r.meta["reason"] for k, r in result.skipped.items()} == {
        "s2": "max_waves",
        "s3": "max_waves",
    }


def test_deadline_skips_everything_pending() -> None:
    result = wave(PARALLEL, {}, time_left_s=0)
    assert result.steps == []
    assert {r.meta["reason"] for r in result.skipped.values()} == {"deadline"}


def test_finished_plan_is_an_empty_wave() -> None:
    done = {s.id: res(s.id) for s in CHAIN.steps}
    assert wave(CHAIN, done).steps == []


def test_dispatch_sends_step_tasks_with_resolved_input() -> None:
    sends = dispatch(
        CHAIN, {"s1": res("s1", output="summary")}, user_text="raw", max_parallel=2, deadline=9.0
    )
    assert isinstance(sends, list)
    (send,) = sends
    assert isinstance(send, Send) and send.node == skill_node_name("b")
    task = send.arg
    assert task.skill_input.text == "summary" and task.skill_input.is_chained
    assert task.deadline_monotonic == 9.0

    first = dispatch(PARALLEL, {}, user_text="raw", max_parallel=2, deadline=9.0)
    assert isinstance(first, list)
    assert [s.arg.skill_input.text for s in first] == ["raw", "raw"]
    assert not first[0].arg.skill_input.is_chained


def test_dispatch_goes_to_composer_when_nothing_is_ready() -> None:
    done = {s.id: res(s.id) for s in CHAIN.steps}
    assert dispatch(CHAIN, done, user_text="", max_parallel=2, deadline=0) == COMPOSER
