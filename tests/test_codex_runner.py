from __future__ import annotations

import pytest

from hermit_agent.codex_runner import (
    is_codex_model,
    normalize_codex_model,
    _normalize_reasoning_effort,
    _prepare_codex_task,
    wait_for_codex_host_reply,
)
from hermit_agent.gateway.task_store import GatewayTaskState
from hermit_agent.config import get_primary_model, get_routing_priority_models, is_model_configured


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


def test_prepare_codex_task_wraps_original_task_with_interactive_guidance():
    task = _prepare_codex_task("Ask exactly one short user question.")

    assert "Hermit interactive-input contract:" in task
    assert "Do not claim that ask_user_question is unavailable." in task
    assert task.endswith("Task:\nAsk exactly one short user question.")


def test_prepare_codex_task_handles_empty_body():
    task = _prepare_codex_task("")

    assert "Hermit interactive-input contract:" in task
    assert "Task:\n" not in task


def test_wait_for_codex_host_reply_uses_plain_text_user_input_request(monkeypatch):
    import hermit_agent.codex_runner as codex_runner

    captured = {}

    class DummySSE:
        def __init__(self):
            self.events = []

        def publish_threadsafe(self, task_id, event):
            self.events.append((task_id, event.type, event.question, event.tool_name))

    def fake_await(prompt, env=None):
        captured["prompt"] = prompt
        return "staging"

    monkeypatch.setattr(
        codex_runner,
        "await_attached_codex_app_server_response",
        fake_await,
    )
    monkeypatch.setattr(
        codex_runner,
        "load_codex_channels_settings",
        lambda cfg, cwd: type("Settings", (), {"enabled": False})(),
    )

    state = GatewayTaskState(task_id="task-followup")
    sse = DummySSE()

    answer = wait_for_codex_host_reply(
        state=state,
        sse=sse,
        task_id="task-followup",
        question="Which environment should we use?",
        cwd="/tmp",
    )

    assert answer == "staging"
    assert sse.events[0] == ("task-followup", "waiting", "Which environment should we use?", "ask")
    assert captured["prompt"].method == "item/tool/requestUserInput"
    assert captured["prompt"].request_id == "followup-task-followup"
    assert captured["prompt"].params == {
        "questions": [{"id": "followup", "question": "Which environment should we use?"}]
    }


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

        def write_event(self, payload):
            calls.setdefault("log_events", []).append(payload)

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


def test_run_single_model_routes_interview_like_codex_task_to_mcp_session(monkeypatch):
    from hermit_agent.gateway.task_execution import run_single_model

    calls = {}
    state = GatewayTaskState(task_id="interview-task")
    # interview path blocks on _wait_for_gateway_reply(state.reply_queue) — pre-stage an answer
    state.reply_queue.put("staging")

    class DummySSE:
        def publish_threadsafe(self, task_id, event):
            calls.setdefault("events", []).append((task_id, event.type))

    class DummyLog:
        def write_event(self, payload):
            calls.setdefault("log_events", []).append(payload)

    class DummyLLM:
        def __init__(self, *, base_url, model, api_key):
            calls["llm"] = {"base_url": base_url, "model": model, "api_key": api_key}
            self.model = model
            self.fallback_model = None

    class DummySession:
        def __init__(self, **kwargs):
            calls["session_init"] = kwargs

        def set_emitter_handler(self, handler):
            calls["emitter_handler"] = handler

        def run(self, prompt):
            calls["prompt"] = prompt
            state.status = "done"
            state.token_totals = {"prompt_tokens": 11, "completion_tokens": 7}
            return "environment=staging"

    class DummyPermissionChecker:
        def __init__(self, **kwargs):
            calls["permission_checker"] = kwargs

    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.get_routing_priority_models",
        lambda cfg, available_only=True: [{"model": "glm-5.1"}],
    )
    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.is_model_configured",
        lambda model, cfg: model == "glm-5.1",
    )
    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.run_codex_task",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("codex runner should not be used")),
    )

    result = run_single_model(
        task_id="interview-task",
        task="Ask the user which environment to use and wait for the reply.",
        cwd="/tmp",
        selected_model="gpt-5.4",
        reasoning_effort="medium",
        max_turns=4,
        state=state,
        sse=DummySSE(),
        gw_log=DummyLog(),
        cfg={"codex_reasoning_effort": "medium"},
        select_llm_endpoint=lambda model, cfg: ("http://llm.test", "token-1"),
        codex_runner=None,
        llm_factory=DummyLLM,
        session_cls=DummySession,
        permission_checker_cls=DummyPermissionChecker,
    )

    assert calls["llm"]["model"] == "glm-5.1"
    assert "which environment" in calls["prompt"].lower()
    assert calls["session_init"]["task_mode"] == "interview"
    assert result["status"] == "done"
    assert result["model"] == "glm-5.1"
    assert any(event.get("type") == "execution_route" and event.get("route") == "mcp_session" for event in calls["log_events"])


def test_run_single_model_raises_when_interview_fallback_model_missing(monkeypatch):
    from hermit_agent.gateway.task_execution import run_single_model

    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.get_routing_priority_models",
        lambda cfg, available_only=True: [],
    )
    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.is_model_configured",
        lambda model, cfg: False,
    )

    with pytest.raises(RuntimeError, match="Interview-style Codex task requires a non-Codex configured model"):
        run_single_model(
            task_id="interview-task-missing",
            task="Ask exactly one short user question before continuing.",
            cwd="/tmp",
            selected_model="gpt-5.4",
            reasoning_effort="medium",
            max_turns=4,
            state=GatewayTaskState(task_id="interview-task-missing"),
            sse=type("SSE", (), {"publish_threadsafe": lambda *args, **kwargs: None})(),
            gw_log=type("Log", (), {"write_event": lambda *args, **kwargs: None})(),
            cfg={"model": "gpt-5.4", "codex_reasoning_effort": "medium"},
            select_llm_endpoint=lambda model, cfg: ("", ""),
            codex_runner=None,
            llm_factory=None,
            session_cls=None,
            permission_checker_cls=object,
        )


def test_run_single_model_honors_explicit_codex_execution_hint(monkeypatch):
    from hermit_agent.gateway.task_execution import run_single_model

    calls = {}

    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.run_codex_task",
        lambda **kwargs: calls.setdefault("codex_kwargs", kwargs) or {
            "status": "done",
            "token_totals": {"prompt_tokens": 3, "completion_tokens": 1},
            "result": "done",
            "model": kwargs["model"],
        },
    )

    result = run_single_model(
        task_id="codex-hint-task",
        task="hermit-execution-mode: codex\nAsk the user which environment to use and wait for the reply.",
        cwd="/tmp",
        selected_model="gpt-5.4",
        reasoning_effort="medium",
        max_turns=4,
        state=GatewayTaskState(task_id="codex-hint-task"),
        sse=type("SSE", (), {"publish_threadsafe": lambda *args, **kwargs: None})(),
        gw_log=type("Log", (), {"write_event": lambda *args, **kwargs: calls.setdefault('logged', []).append(args[1] if len(args) > 1 else kwargs)})(),
        cfg={"codex_reasoning_effort": "medium", "codex_command": "codex"},
        select_llm_endpoint=lambda model, cfg: ("http://llm.test", "token-1"),
        codex_runner=lambda **kwargs: {
            "status": "done",
            "token_totals": {"prompt_tokens": 3, "completion_tokens": 1},
            "result": "done",
            "model": kwargs["model"],
        },
        llm_factory=None,
        session_cls=None,
        permission_checker_cls=object,
    )

    assert result["model"] == "gpt-5.4"


def test_run_single_model_honors_explicit_interview_execution_hint(monkeypatch):
    from hermit_agent.gateway.task_execution import run_single_model

    calls = {}
    state = GatewayTaskState(task_id="interview-hint-task")
    # interview path blocks on _wait_for_gateway_reply(state.reply_queue) — pre-stage an answer
    state.reply_queue.put("staging")

    class DummyLLM:
        def __init__(self, *, base_url, model, api_key):
            self.model = model
            self.fallback_model = None
            calls["model"] = model

    class DummySession:
        def __init__(self, **kwargs):
            calls["session_init"] = kwargs

        def set_emitter_handler(self, handler):
            return None

        def run(self, prompt):
            calls["prompt"] = prompt
            state.status = "done"
            return "environment=staging"

    class DummyPermissionChecker:
        def __init__(self, **kwargs):
            return None

    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.get_routing_priority_models",
        lambda cfg, available_only=True: [{"model": "glm-5.1"}],
    )
    monkeypatch.setattr(
        "hermit_agent.gateway.task_execution.is_model_configured",
        lambda model, cfg: model == "glm-5.1",
    )

    result = run_single_model(
        task_id="interview-hint-task",
        task="hermit-execution-mode: interview\nDo normal implementation work.",
        cwd="/tmp",
        selected_model="gpt-5.4",
        reasoning_effort="medium",
        max_turns=4,
        state=state,
        sse=type("SSE", (), {"publish_threadsafe": lambda *args, **kwargs: None})(),
        gw_log=type("Log", (), {"write_event": lambda *args, **kwargs: None})(),
        cfg={"codex_reasoning_effort": "medium"},
        select_llm_endpoint=lambda model, cfg: ("http://llm.test", "token-1"),
        codex_runner=lambda **kwargs: (_ for _ in ()).throw(AssertionError("codex runner should not be used")),
        llm_factory=DummyLLM,
        session_cls=DummySession,
        permission_checker_cls=DummyPermissionChecker,
    )

    assert result["model"] == "glm-5.1"
    assert "hermit-execution-mode" not in calls["prompt"]
    assert calls["session_init"]["task_mode"] == "interview"


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
        "-c",
        f'mcp_servers.hermit_ask_user.command="{codex_runner.sys.executable}"',
        "-c",
        'mcp_servers.hermit_ask_user.args=["-m", "hermit_agent.codex_ask_mcp"]',
        "--disable",
        "codex_hooks",
        "--listen",
        "stdio://",
    ]


def test_codex_client_write_message_uses_json_rpc_stream_writer():
    import hermit_agent.codex_runner as codex_runner

    events = []

    class Stdin:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    class DummyProcess:
        def __init__(self):
            self.stdin = Stdin()
            self.stdout = None
            self.stderr = None

    client = codex_runner.CodexAppServerClient(
        command="codex",
        cwd="/tmp",
        model="gpt-5.3-codex",
        reasoning_effort="medium",
        state=GatewayTaskState(task_id="t"),
        sse=object(),
        task_id="task-id",
    )
    client._process = DummyProcess()

    client._write_message({"id": "req-write", "method": "initialized", "params": {}})

    assert events == [
        ("write", '{"id": "req-write", "method": "initialized", "params": {}}\n'),
        ("flush", ""),
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


def test_auto_model_chain_order_prefers_codex_then_zai_then_local(monkeypatch):
    from hermit_agent.gateway import task_runner

    monkeypatch.setattr("hermit_agent.config.shutil.which", lambda cmd: "/usr/bin/" + cmd)
    cfg = {
        "codex_default_model": "gpt-5.4",
        "codex_reasoning_effort": "medium",
        "model": "glm-5.1",
        "providers": {
            "z.ai": {"base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": "k"},
        },
        "local_model": "qwen3-coder:30b",
    }
    assert task_runner._auto_model_chain(cfg) == [
        {"model": "gpt-5.4", "reasoning_effort": "medium"},
        {"model": "glm-5.1"},
        {"model": "qwen3-coder:30b"},
    ]


def test_auto_model_chain_uses_routing_priority_models_from_settings(monkeypatch):
    from hermit_agent.gateway import task_runner

    monkeypatch.setattr("hermit_agent.config.shutil.which", lambda cmd: "/usr/bin/" + cmd)
    cfg = {
        "providers": {
            "z.ai": {"base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": "k"},
        },
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


def test_auto_model_chain_deduplicates_models_preserving_first_reasoning_effort(monkeypatch):
    from hermit_agent.gateway import task_runner

    monkeypatch.setattr("hermit_agent.config.shutil.which", lambda cmd: "/usr/bin/" + cmd)
    cfg = {
        "providers": {
            "z.ai": {"base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": "k"},
        },
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


def test_get_routing_priority_models_skips_unconfigured_providers(monkeypatch):
    cfg = {
        "codex_command": "codex",
        "ollama_url": "http://localhost:11434/v1",
        "providers": {
            "z.ai": {"base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": "k"},
        },
        "routing": {
            "priority_models": [
                {"model": "gpt-5.4", "reasoning_effort": "medium"},
                {"model": "glm-5.1"},
                {"model": "qwen3-coder:30b"},
            ]
        },
    }
    monkeypatch.setattr("hermit_agent.config.shutil.which", lambda cmd: None if cmd == "codex" else None)

    assert get_routing_priority_models(cfg, available_only=True) == [
        {"model": "glm-5.1"},
    ]


def test_get_primary_model_prefers_first_available(monkeypatch):
    cfg = {
        "codex_command": "codex",
        "providers": {"z.ai": {"base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": "k"}},
        "routing": {
            "priority_models": [
                {"model": "gpt-5.4", "reasoning_effort": "medium"},
                {"model": "glm-5.1"},
            ]
        },
        "model": "glm-5.1",
    }
    monkeypatch.setattr("hermit_agent.config.shutil.which", lambda cmd: None)

    assert get_primary_model(cfg, available_only=True) == "glm-5.1"


def test_is_model_configured_recognizes_remote_ollama_without_local_binary(monkeypatch):
    cfg = {"ollama_url": "https://ollama.example.com/v1"}
    monkeypatch.setattr("hermit_agent.config.shutil.which", lambda cmd: None)
    assert is_model_configured("qwen3-coder:30b", cfg) is True


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
    monkeypatch.setattr(
        config_mod,
        "is_model_configured",
        lambda model, cfg: model in {"gpt-5.4", "glm-5.1"},
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


def test_wait_for_reply_accepts_codex_channels_response(monkeypatch):
    import hermit_agent.codex_runner as codex_runner
    from hermit_agent.codex_channels_adapter import CodexChannelsSettings

    calls = {"started": 0, "terminated": 0}

    class FakeSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction

        def start(self):
            calls["started"] += 1

        def poll_response(self):
            return "Always allow (session)"

        def terminate(self):
            calls["terminated"] += 1

    class DummySSE:
        def __init__(self):
            self.events = []

        def publish_threadsafe(self, task_id, event):
            self.events.append((task_id, event.type, event.question, event.message, event.tool_name))

    monkeypatch.setattr(codex_runner, "load_codex_channels_settings", lambda cfg, cwd: CodexChannelsSettings(enabled=True, state_file="/tmp/state.json"))
    monkeypatch.setattr(codex_runner, "CodexChannelsWaitSession", FakeSession)

    state = GatewayTaskState(task_id="task-1")
    sse = DummySSE()
    answer = codex_runner._wait_for_reply(
        state=state,
        sse=sse,
        task_id="task-1",
        question="Allow?",
        options=["Yes", "No"],
        kind="permission_ask",
        method="item/commandExecution/requestApproval",
        request_id="req-1",
        thread_id="thr-1",
        turn_id="turn-1",
        codex_channels_cfg={"enabled": True},
    )

    assert answer == "Always allow (session)"
    assert calls["started"] == 1
    assert calls["terminated"] == 1
    assert calls["interaction"]["id"] == "hermit-task-1-req-1"
    assert sse.events[0] == ("task-1", "permission_ask", "Allow?", "", "bash")
    assert sse.events[-1][1] == "reply_ack"
    assert state.waiting_prompt is None


def test_wait_for_reply_falls_back_to_reply_queue_when_codex_channels_session_is_silent(monkeypatch):
    import hermit_agent.codex_runner as codex_runner
    from hermit_agent.codex_channels_adapter import CodexChannelsSettings

    class SilentSession:
        def __init__(self, *, settings, interaction):
            self._calls = 0

        def start(self):
            return None

        def poll_response(self):
            self._calls += 1
            return None

        def terminate(self):
            return None

    class DummySSE:
        def __init__(self):
            self.events = []

        def publish_threadsafe(self, task_id, event):
            self.events.append((task_id, event.type, event.tool_name))

    monkeypatch.setattr(codex_runner, "load_codex_channels_settings", lambda cfg, cwd: CodexChannelsSettings(enabled=True, state_file="/tmp/state.json", source_path="/tmp/codex-channels"))
    monkeypatch.setattr(codex_runner, "CodexChannelsWaitSession", SilentSession)

    state = GatewayTaskState(task_id="task-2")
    state.reply_queue.put("manual-answer")
    sse = DummySSE()

    answer = codex_runner._wait_for_reply(
        state=state,
        sse=sse,
        task_id="task-2",
        question="Continue?",
        options=["Yes", "No"],
        kind="waiting",
        method="item/tool/requestUserInput",
        request_id="req-2",
        thread_id="thr-2",
        turn_id="turn-2",
        codex_channels_cfg={"enabled": True},
        cwd="/tmp/worktree",
    )

    assert answer == "manual-answer"
    assert sse.events[0] == ("task-2", "waiting", "ask")
    assert sse.events[-1] == ("task-2", "reply_ack", "")
    assert state.waiting_prompt is None


def test_wait_for_reply_prefers_attached_codex_app_server_roundtrip(monkeypatch):
    import hermit_agent.codex_runner as codex_runner

    captured = {}

    class DummySSE:
        def __init__(self):
            self.events = []

        def publish_threadsafe(self, task_id, event):
            self.events.append((task_id, event.type, event.tool_name))

    def fake_await(prompt, env=None):
        captured["prompt"] = prompt
        return "staging"

    monkeypatch.setattr(
        codex_runner,
        "await_attached_codex_app_server_response",
        fake_await,
    )
    monkeypatch.setattr(
        codex_runner,
        "load_codex_channels_settings",
        lambda cfg, cwd: type("Settings", (), {"enabled": False})(),
    )

    state = GatewayTaskState(task_id="task-attached")
    sse = DummySSE()

    answer = codex_runner._wait_for_reply(
        state=state,
        sse=sse,
        task_id="task-attached",
        question="Where?",
        options=["staging", "prod"],
        kind="waiting",
        method="item/tool/requestUserInput",
        request_id="req-attached",
        thread_id="thr-attached",
        turn_id="turn-attached",
        request_params={"questions": [{"id": "target", "question": "Where?"}]},
        codex_channels_cfg={},
        cwd="/tmp",
    )

    assert answer == "staging"
    assert sse.events[0] == ("task-attached", "waiting", "ask")
    assert sse.events[-1] == ("task-attached", "reply_ack", "")
    assert state.question_queue.get_nowait() == {
        "question": "Where?",
        "options": ["staging", "prod"],
        "tool_name": "ask",
        "method": "item/tool/requestUserInput",
    }
    assert captured["prompt"].thread_id == "thr-attached"
    assert captured["prompt"].turn_id == "turn-attached"
    assert captured["prompt"].params == {"questions": [{"id": "target", "question": "Where?"}]}
    assert state.waiting_kind is None
    assert state.waiting_prompt is None
