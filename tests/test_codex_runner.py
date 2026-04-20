from __future__ import annotations

from hermit_agent.codex_runner import (
    is_codex_model,
    normalize_codex_model,
    _normalize_reasoning_effort,
)
from hermit_agent.gateway.task_store import GatewayTaskState


def test_is_codex_model_detects_supported_aliases():
    assert is_codex_model("gpt-5.3-codex") is True
    assert is_codex_model("gpt-5.4") is True
    assert is_codex_model("codex/gpt-5.3-codex") is True
    assert is_codex_model("codex") is True
    assert is_codex_model("glm-5.1") is False
    assert is_codex_model("qwen3-coder:30b") is False


def test_normalize_codex_model_strips_provider_prefix():
    assert normalize_codex_model("codex/gpt-5.3-codex") == "gpt-5.3-codex"
    assert normalize_codex_model("gpt-5.2-codex") == "gpt-5.2-codex"
    assert normalize_codex_model("codex") == "gpt-5.4"


def test_normalize_reasoning_effort_accepts_supported_values():
    assert _normalize_reasoning_effort("medium") == "medium"
    assert _normalize_reasoning_effort("XHIGH") == "xhigh"
    assert _normalize_reasoning_effort("bogus") is None


def test_task_runner_codex_branch_uses_codex_backend(monkeypatch):
    from hermit_agent import config as config_mod
    from hermit_agent.gateway import task_runner

    state = GatewayTaskState(task_id="codex-task")
    calls = {}

    class DummySSE:
        def publish_threadsafe(self, task_id, event):
            calls.setdefault("events", []).append((task_id, event))

    class DummyLog:
        def __init__(self, *args, **kwargs):
            calls["log_init"] = {"args": args, "kwargs": kwargs}

        def mark_completed(self, token_totals=None):
            calls["log_completed"] = token_totals

        def mark_crashed(self, error):
            calls["log_crashed"] = error

    monkeypatch.setattr(task_runner, "release_worker_slot", lambda: calls.setdefault("released", True))
    monkeypatch.setattr(
        config_mod,
        "load_settings",
        lambda cwd=None: {"codex_command": "codex", "codex_reasoning_effort": "medium"},
    )
    monkeypatch.setattr(task_runner, "GatewaySessionLog", DummyLog)

    def fake_run_codex_task(**kwargs):
        calls["kwargs"] = kwargs
        kwargs["state"].token_totals = {"prompt_tokens": 7, "completion_tokens": 3}
        kwargs["state"].result = "done"
        return {"token_totals": kwargs["state"].token_totals, "status": "done", "model": kwargs["model"], "result": "done"}

    monkeypatch.setattr(task_runner, "run_codex_task", fake_run_codex_task)

    result = task_runner._run(
        task_id="codex-task",
        task="say hi",
        cwd="/tmp",
        user="tester",
        model="gpt-5.3-codex",
        max_turns=5,
        state=state,
        sse=DummySSE(),
    )

    assert calls["kwargs"]["codex_command"] == "codex"
    assert calls["kwargs"]["model"] == "gpt-5.3-codex"
    assert calls["kwargs"]["reasoning_effort"] == "medium"
    assert result["status"] == "done"
    assert result["token_totals"] == {"prompt_tokens": 7, "completion_tokens": 3}
    assert calls["released"] is True
    assert calls["log_completed"] == {"prompt_tokens": 7, "completion_tokens": 3}


def test_codex_client_launch_uses_clean_app_server_flags(monkeypatch):
    import hermit_agent.codex_runner as codex_runner

    captured = {}

    class DummyProcess:
        def __init__(self):
            self.stdin = None
            self.stdout = None
            self.stderr = None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(codex_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(codex_runner.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())

    client = codex_runner.CodexAppServerClient(
        command="codex",
        cwd="/tmp",
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        state=GatewayTaskState(task_id="t"),
        sse=object(),
        task_id="task-id",
    )
    client._start_process()

    assert captured["args"] == [
        "codex",
        "app-server",
        "-c",
        "mcp_servers={}",
        "--disable",
        "codex_hooks",
        "--listen",
        "stdio://",
    ]


def test_system_error_event_fails_fast():
    import hermit_agent.codex_runner as codex_runner

    client = codex_runner.CodexAppServerClient(
        command="codex",
        cwd="/tmp",
        model="gpt-5.3-codex",
        reasoning_effort=None,
        state=GatewayTaskState(task_id="t"),
        sse=object(),
        task_id="task-id",
    )

    try:
        client._dispatch_message(
            {
                "method": "thread/status/changed",
                "params": {"status": {"type": "systemError"}},
            }
        )
        assert False, "expected CodexTaskFailed"
    except codex_runner.CodexTaskFailed as exc:
        assert "systemError" in str(exc)


def test_thread_idle_with_result_completes_drain():
    import hermit_agent.codex_runner as codex_runner

    client = codex_runner.CodexAppServerClient(
        command="codex",
        cwd="/tmp",
        model="gpt-5.3-codex",
        reasoning_effort=None,
        state=GatewayTaskState(task_id="t"),
        sse=object(),
        task_id="task-id",
    )
    client._latest_result = "Hello."

    result = client._dispatch_message(
        {"method": "thread/status/changed", "params": {"status": {"type": "idle"}}}
    )
    assert result is True


def test_thread_idle_without_result_does_not_complete():
    import hermit_agent.codex_runner as codex_runner

    client = codex_runner.CodexAppServerClient(
        command="codex",
        cwd="/tmp",
        model="gpt-5.3-codex",
        reasoning_effort=None,
        state=GatewayTaskState(task_id="t"),
        sse=object(),
        task_id="task-id",
    )

    result = client._dispatch_message(
        {"method": "thread/status/changed", "params": {"status": {"type": "idle"}}}
    )
    assert result is False


def test_rate_limit_event_fails_fast_when_out_of_credits():
    import hermit_agent.codex_runner as codex_runner

    client = codex_runner.CodexAppServerClient(
        command="codex",
        cwd="/tmp",
        model="gpt-5.3-codex",
        reasoning_effort=None,
        state=GatewayTaskState(task_id="t"),
        sse=object(),
        task_id="task-id",
    )

    try:
        client._dispatch_message(
            {
                "method": "account/rateLimits/updated",
                "params": {
                    "rateLimits": {
                        "primary": {"usedPercent": 100},
                        "credits": {"hasCredits": False},
                    }
                },
            }
        )
        assert False, "expected CodexTaskFailed"
    except codex_runner.CodexTaskFailed as exc:
        assert "rate-limited or out of credits" in str(exc)


def test_auto_model_chain_order_prefers_codex_then_zai_then_local():
    from hermit_agent.gateway import task_runner

    cfg = {
        "codex_default_model": "gpt-5.4",
        "codex_reasoning_effort": "medium",
        "model": "glm-5.1",
        "local_model": "qwen3-coder:30b",
    }
    assert task_runner._auto_model_chain(cfg) == [
        {"model": "gpt-5.4", "reasoning_effort": "medium"},
        {"model": "glm-5.1"},
        {"model": "qwen3-coder:30b"},
    ]


def test_auto_model_chain_uses_routing_priority_models_from_settings():
    from hermit_agent.gateway import task_runner

    cfg = {
        "routing": {
            "priority_models": [
                {"model": "glm-5.1"},
                {"model": "gpt-5.4", "reasoning_effort": "high"},
                {"model": "qwen3-coder:30b"},
            ]
        }
    }
    assert task_runner._auto_model_chain(cfg) == [
        {"model": "glm-5.1"},
        {"model": "gpt-5.4", "reasoning_effort": "high"},
        {"model": "qwen3-coder:30b"},
    ]


def test_auto_model_chain_deduplicates_models_preserving_first_reasoning_effort():
    from hermit_agent.gateway import task_runner

    cfg = {
        "routing": {
            "priority_models": [
                {"model": "gpt-5.4", "reasoning_effort": "medium"},
                {"model": "gpt-5.4", "reasoning_effort": "high"},
                "glm-5.1",
            ]
        }
    }
    assert task_runner._auto_model_chain(cfg) == [
        {"model": "gpt-5.4", "reasoning_effort": "medium"},
        {"model": "glm-5.1"},
    ]


def test_auto_route_falls_back_to_zai_when_codex_unavailable(monkeypatch):
    from hermit_agent.gateway import task_runner

    state = GatewayTaskState(task_id="auto-task")
    calls = {"codex": 0, "session_runs": 0}

    class DummySSE:
        def publish_threadsafe(self, task_id, event):
            calls.setdefault("events", []).append((task_id, event.type))

    class DummyLog:
        def __init__(self, *args, **kwargs):
            pass

        def write_event(self, payload):
            calls.setdefault("log_events", []).append(payload)

        def mark_completed(self, token_totals=None):
            calls["completed"] = token_totals

        def mark_crashed(self, error):
            calls["crashed"] = error

    class DummySession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def set_emitter_handler(self, *_a, **_k):
            return None

        def run(self, _task):
            calls["session_runs"] += 1

    monkeypatch.setattr(task_runner, "GatewaySessionLog", DummyLog)
    monkeypatch.setattr(task_runner, "release_worker_slot", lambda: calls.setdefault("released", True))
    monkeypatch.setattr(task_runner, "MCPAgentSession", DummySession)
    monkeypatch.setattr(task_runner, "GatewayPermissionChecker", lambda **_k: object())

    def fake_codex(**kwargs):
        calls["codex"] += 1
        raise RuntimeError("Codex account is currently rate-limited or out of credits")

    monkeypatch.setattr(task_runner, "run_codex_task", fake_codex)

    from hermit_agent import config as config_mod

    monkeypatch.setattr(
        config_mod,
        "load_settings",
        lambda cwd=None: {
            "codex_command": "codex",
            "codex_default_model": "gpt-5.4",
            "codex_reasoning_effort": "medium",
            "model": "glm-5.1",
            "local_model": "qwen3-coder:30b",
            "providers": {"z.ai": {"base_url": "https://example.invalid", "api_key": "k"}},
        },
    )
    monkeypatch.setattr(
        config_mod,
        "select_llm_endpoint",
        lambda model, cfg: ("https://example.invalid", "k") if model == "glm-5.1" else ("", ""),
    )

    monkeypatch.setattr(task_runner, "create_llm_client", lambda **_k: object())

    result = task_runner._run(
        task_id="auto-task",
        task="hello",
        cwd="/tmp",
        user="tester",
        model="__auto__",
        max_turns=3,
        state=state,
        sse=DummySSE(),
    )

    assert calls["codex"] == 1
    assert calls["session_runs"] == 1
    assert result["status"] == "done"
    assert result["model"] == "glm-5.1"
    assert result["auto_route"]["selected"] == "glm-5.1"
    assert calls["released"] is True


def test_explicit_unavailable_model_returns_unavailable_message(monkeypatch):
    from hermit_agent.gateway import task_runner
    from hermit_agent import config as config_mod

    state = GatewayTaskState(task_id="explicit-task")
    calls = {}

    class DummySSE:
        def publish_threadsafe(self, _task_id, event):
            calls.setdefault("events", []).append(event.type)

    class DummyLog:
        def __init__(self, *args, **kwargs):
            pass

        def write_event(self, payload):
            calls.setdefault("log", []).append(payload)

        def mark_completed(self, token_totals=None):
            calls["completed"] = token_totals

        def mark_crashed(self, error):
            calls["crashed"] = error

    monkeypatch.setattr(task_runner, "GatewaySessionLog", DummyLog)
    monkeypatch.setattr(task_runner, "release_worker_slot", lambda: calls.setdefault("released", True))
    monkeypatch.setattr(config_mod, "load_settings", lambda cwd=None: {"codex_command": "codex"})
    monkeypatch.setattr(task_runner, "run_codex_task", lambda **_k: (_ for _ in ()).throw(RuntimeError("out of credits")))

    result = task_runner._run(
        task_id="explicit-task",
        task="hello",
        cwd="/tmp",
        user="tester",
        model="gpt-5.3-codex",
        max_turns=3,
        state=state,
        sse=DummySSE(),
    )

    assert result["status"] == "error"
    assert state.status == "error"
    assert "Requested model unavailable: gpt-5.3-codex" in state.result
    assert calls["released"] is True
