from __future__ import annotations

import pytest

from hermit_agent.orchestration import resolve_orchestration, review_requires_attention


def test_default_orchestration_preserves_single_executor_cost_profile() -> None:
    plan = resolve_orchestration("Rename one variable and run the focused test.", {})

    assert plan.stages == ("executor",)
    assert plan.quality_gate is False
    assert plan.allow_parallel_writes is False


def test_auto_orchestration_adds_read_only_quality_stages_for_complex_work() -> None:
    plan = resolve_orchestration(
        "Refactor the authentication architecture and migrate the database schema safely.",
        {"orchestration": {"mode": "auto", "max_agents": 3}},
    )

    assert plan.stages == ("planner", "executor", "reviewer")
    assert plan.quality_gate is True
    assert plan.allow_parallel_writes is False


def test_auto_orchestration_does_not_spend_extra_agents_on_small_work() -> None:
    plan = resolve_orchestration("Correct a typo in README.", {"orchestration": {"mode": "auto"}})

    assert plan.stages == ("executor",)
    assert plan.reason == "task does not justify extra agent cost"


def test_parallel_writes_are_disabled_even_if_a_settings_file_requests_them() -> None:
    plan = resolve_orchestration(
        "Refactor the authentication architecture.",
        {"orchestration": {"mode": "auto", "allow_parallel_writes": True}},
    )

    assert plan.allow_parallel_writes is False


def test_quality_gate_fails_closed_for_an_inconclusive_or_failed_review() -> None:
    assert review_requires_attention("") is True
    assert review_requires_attention("VERDICT: NEEDS_REVIEW\nPotential regression") is True
    assert review_requires_attention("VERDICT: PASS\nNo material issue found") is False


def test_auto_quality_gate_uses_the_same_mcp_executor_path_for_every_model(monkeypatch) -> None:
    from hermit_agent.gateway.task_execution import run_single_model
    from hermit_agent.gateway.task_store import GatewayTaskState

    plan = resolve_orchestration(
        "Refactor the authentication architecture without breaking existing callers.",
        {"orchestration": {"mode": "auto"}},
    )

    state = GatewayTaskState(task_id="quality-gate-route")
    monkeypatch.setattr("hermit_agent.gateway.task_execution._run_readonly_role", lambda **_kwargs: "VERDICT: PASS")

    class DummySession:
        _agent = None

        def __init__(self, **_kwargs) -> None:
            pass

        def set_emitter_handler(self, _handler) -> None:
            pass

        def run(self, _prompt: str) -> str:
            state.result = "done"
            return state.result

    result = run_single_model(
        task_id="quality-gate-route",
        task="Refactor the authentication architecture without breaking existing callers.",
        cwd="/tmp",
        selected_model="gpt-5.4",
        reasoning_effort=None,
        max_turns=10,
        state=state,
        sse=type("SSE", (), {"publish_threadsafe": lambda *_args, **_kwargs: None})(),
        gw_log=type("Log", (), {"write_event": lambda *_args, **_kwargs: None})(),
        cfg={},
        select_llm_endpoint=lambda _model, _cfg: ("https://llm.example.com/v1", "key"),
        llm_factory=lambda **_kwargs: type("LLM", (), {"model": "gpt-5.4"})(),
        session_cls=DummySession,
        permission_checker_cls=lambda **_kwargs: object(),
        orchestration_plan=plan,
    )

    assert result["status"] == "done"


def test_complex_auto_task_is_not_marked_done_when_review_needs_attention(monkeypatch) -> None:
    from hermit_agent.gateway.task_execution import run_single_model
    from hermit_agent.gateway.task_store import GatewayTaskState

    state = GatewayTaskState(task_id="quality-gate")
    plan = resolve_orchestration(
        "Refactor the authentication architecture without breaking existing callers.",
        {"orchestration": {"mode": "auto"}},
    )
    calls: list[str] = []

    class DummyLLM:
        model = "glm-5.1"

    class DummySession:
        _agent = None

        def __init__(self, **_kwargs) -> None:
            pass

        def set_emitter_handler(self, _handler) -> None:
            pass

        def run(self, prompt: str) -> str:
            calls.append(prompt)
            state.result = "executor completed the change"
            return state.result

    class DummySSE:
        def publish_threadsafe(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution._run_readonly_role",
        lambda **kwargs: "implementation plan" if "planning agent" in kwargs["system_prompt"] else "VERDICT: NEEDS_REVIEW\nMissing regression test",
    )

    result = run_single_model(
        task_id="quality-gate",
        task="Refactor the authentication architecture without breaking existing callers.",
        cwd="/tmp",
        selected_model="glm-5.1",
        reasoning_effort=None,
        max_turns=10,
        state=state,
        sse=DummySSE(),
        gw_log=type("Log", (), {"write_event": lambda *_args, **_kwargs: None})(),
        cfg={},
        select_llm_endpoint=lambda _model, _cfg: ("https://llm.example.com/v1", "key"),
        llm_factory=lambda **_kwargs: DummyLLM(),
        session_cls=DummySession,
        permission_checker_cls=lambda **_kwargs: object(),
        orchestration_plan=plan,
    )

    assert "<implementation_plan>" in calls[0]
    assert result["status"] == "needs_review"
    assert state.orchestration["completed_stages"] == ["planner", "executor", "reviewer"]
    assert "Missing regression test" in str(state.result)
