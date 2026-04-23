from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace


class _FakeWriteStream:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


class _FakeSession:
    def __init__(self):
        self._write_stream = _FakeWriteStream()


def _start_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _stop_loop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


def test_channel_notifications_buffer_until_session_is_attached():
    import hermit_agent.mcp_channel as m

    with m._session_lock:
        m._current_session = None
        m._current_loop = None
        m._pending_channel_notifications.clear()

    m._fire_channel_notification_sync("hello", {"task_id": "t1", "kind": "waiting"})

    with m._session_lock:
        assert len(m._pending_channel_notifications) == 1

    loop, thread = _start_loop()
    session = _FakeSession()
    try:
        m._set_active_session(session, loop)
        deadline = time.time() + 2
        while time.time() < deadline and not session._write_stream.sent:
            time.sleep(0.01)

        assert session._write_stream.sent
        sent_message = session._write_stream.sent[0].message.model_dump(mode="json", exclude_none=True)
        assert sent_message["method"] == "notifications/claude/channel"
        assert sent_message["params"]["content"] == "hello"
        assert sent_message["params"]["meta"]["task_id"] == "t1"
        assert sent_message["params"]["meta"]["kind"] == "waiting"
        with m._session_lock:
            assert not m._pending_channel_notifications
    finally:
        _stop_loop(loop, thread)
        with m._session_lock:
            m._current_session = None
            m._current_loop = None
            m._pending_channel_notifications.clear()


def test_notify_channel_starts_codex_channels_wait_when_enabled(monkeypatch):
    import hermit_agent.mcp_channel as m

    class FakeSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction

        def start(self):
            calls["session_started"] = True

        def terminate(self):
            calls["session_terminated"] = True

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            calls["thread"] = {"target": target, "args": args, "name": name, "daemon": daemon}

        def start(self):
            calls["thread_started"] = True

    calls = {}
    monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: calls.setdefault("notification", (content, meta)))
    monkeypatch.setattr(m, "_notify_visible_prompt", lambda **kwargs: calls.setdefault("visible_prompt", kwargs))
    monkeypatch.setattr(m, "load_settings", lambda cwd=None: {"codex_channels": {"enabled": True}})
    monkeypatch.setattr(m, "load_codex_channels_settings", lambda cfg, cwd: SimpleNamespace(enabled=True))
    monkeypatch.setattr(m, "CodexChannelsWaitSession", FakeSession)
    monkeypatch.setattr(m.threading, "Thread", FakeThread)

    try:
        m._notify_channel("task-123", "[Permission request] Continue?", ["Yes", "No"], prompt_kind="permission_ask", tool_name="bash")
        assert calls["notification"][0] == "[Permission request] Continue?"
        assert calls["notification"][1]["prompt_kind"] == "permission_ask"
        assert calls["notification"][1]["tool_name"] == "bash"
        assert calls["visible_prompt"]["task_id"] == "task-123"
        assert calls["session_started"] is True
        assert calls["thread_started"] is True
        assert calls["interaction"]["kind"] == "approval_request"
        with m._codex_channel_waits_lock:
            assert "task-123" in m._codex_channel_waits
    finally:
        with m._codex_channel_waits_lock:
            m._codex_channel_waits.clear()


def test_bridge_codex_channels_reply_posts_gateway_reply_and_cleans_up(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {}

    class FakeSession:
        def poll_response(self):
            return "approved"

        def terminate(self):
            calls["terminated"] = calls.get("terminated", 0) + 1

    monkeypatch.setattr(m, "_gateway_reply", lambda task_id, message: calls.setdefault("reply", (task_id, message)) or True)
    session = FakeSession()

    with m._codex_channel_waits_lock:
        m._codex_channel_waits["task-9"] = session

    m._bridge_codex_channels_reply("task-9", session, poll_interval=0.0)

    assert calls["reply"] == ("task-9", "approved")
    assert calls["terminated"] == 1
    with m._codex_channel_waits_lock:
        assert "task-9" not in m._codex_channel_waits


def test_notify_running_stops_codex_channels_wait(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {}

    class FakeSession:
        def terminate(self):
            calls["terminated"] = True

    monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: calls.setdefault("notification", (content, meta)))
    monkeypatch.setattr(m, "_clear_visible_prompt_notification", lambda task_id: calls.setdefault("cleared", task_id))
    with m._codex_channel_waits_lock:
        m._codex_channel_waits["task-run"] = FakeSession()

    m._notify_running("task-run")

    assert calls["notification"][1]["kind"] == "running"
    assert calls["terminated"] is True
    assert calls["cleared"] == "task-run"
    with m._codex_channel_waits_lock:
        assert "task-run" not in m._codex_channel_waits


def test_build_codex_channels_wait_interaction_preserves_method_specific_kind():
    import hermit_agent.mcp_channel as m

    permissions_prompt = m.create_interactive_prompt(
        task_id="task-method-1",
        question="Permissions?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
        method="item/permissions/requestApproval",
        request_id="req-method-1",
    )
    elicitation_prompt = m.create_interactive_prompt(
        task_id="task-method-2",
        question="Need URL",
        options=["Submit", "Cancel"],
        prompt_kind="waiting",
        method="mcpServer/elicitation/request",
        request_id="req-method-2",
    )

    assert m._build_codex_channels_wait_interaction(permissions_prompt)["kind"] == "permissions_request"
    assert m._build_codex_channels_wait_interaction(elicitation_prompt)["kind"] == "elicitation_request"


def test_codex_channels_wait_uses_task_specific_cwd_for_settings(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {}

    class FakeSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction

        def start(self):
            calls["session_started"] = True

        def terminate(self):
            calls["terminated"] = True

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            calls["thread_args"] = args

        def start(self):
            calls["thread_started"] = True

    monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: None)

    def fake_load_settings(cwd=None):
        calls["load_settings_cwd"] = cwd
        return {"codex_channels": {"enabled": True}}

    def fake_load_codex_channels_settings(cfg, cwd):
        calls["load_codex_channels_cwd"] = cwd
        return SimpleNamespace(enabled=True)

    monkeypatch.setattr(m, "load_settings", fake_load_settings)
    monkeypatch.setattr(m, "load_codex_channels_settings", fake_load_codex_channels_settings)
    monkeypatch.setattr(m, "build_interaction", lambda **kwargs: {"interaction": kwargs})
    monkeypatch.setattr(m, "CodexChannelsWaitSession", FakeSession)
    monkeypatch.setattr(m.threading, "Thread", FakeThread)

    try:
        m._remember_task_context("task-cwd", "/tmp/project-a")
        m._notify_channel("task-cwd", "Need input", ["A"], prompt_kind="waiting", tool_name="ask")
        assert calls["load_settings_cwd"] == "/tmp/project-a"
        assert calls["load_codex_channels_cwd"] == "/tmp/project-a"
        assert calls["session_started"] is True
        assert calls["thread_started"] is True
    finally:
        with m._codex_channel_waits_lock:
            m._codex_channel_waits.clear()
        m._forget_task_context("task-cwd")


def test_notify_done_clears_task_context(monkeypatch):
    import hermit_agent.mcp_channel as m

    monkeypatch_calls = {}
    m._remember_task_context("task-finish", "/tmp/project-b")
    try:
        monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: monkeypatch_calls.setdefault("meta", meta))
        monkeypatch.setattr(m, "_clear_visible_prompt_notification", lambda task_id: monkeypatch_calls.setdefault("cleared", task_id))
        m._notify_done("task-finish", "done")
        with m._task_contexts_lock:
            assert "task-finish" not in m._task_contexts
        assert monkeypatch_calls["cleared"] == "task-finish"
    finally:
        m._forget_task_context("task-finish")


def test_build_interactive_sink_accepts_optional_app_server_sink(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []

    class BaseSink:
        def __init__(self, name):
            self.name = name

        def notify(self, prompt):
            calls.append(("notify", self.name, prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", self.name, task_id))

    class OptionalSink:
        def notify(self, prompt):
            calls.append(("notify", "optional", prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", "optional", task_id))

    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink("claude"))
    monkeypatch.setattr(m, "_codex_channels_sink", BaseSink("channels"))

    composite = m._build_interactive_sink(app_server_sink=OptionalSink())
    composite.notify(m.create_interactive_prompt(task_id="task-extra", question="Q", options=[]))
    composite.clear("task-extra")

    assert ("notify", "optional", "task-extra") in calls
    assert ("clear", "optional", "task-extra") in calls
    assert ("notify", "channels", "task-extra") not in calls
    assert ("clear", "channels", "task-extra") not in calls


def test_build_interactive_sink_accepts_app_server_transport(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []

    class BaseSink:
        def __init__(self, name):
            self.name = name

        def notify(self, prompt):
            calls.append(("notify", self.name, prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", self.name, task_id))

    class Transport:
        def send_request(self, request):
            calls.append(("transport", request["id"], request["method"]))
            return request

    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink("claude"))
    monkeypatch.setattr(m, "_codex_channels_sink", BaseSink("channels"))

    composite = m._build_interactive_sink(app_server_transport=Transport())
    composite.notify(
        m.create_interactive_prompt(
            task_id="task-transport",
            question="Approve?",
            options=["Yes"],
            method="item/fileChange/requestApproval",
            request_id="req-transport",
            params={"reason": "Need approval"},
        )
    )
    composite.clear("task-transport")

    assert ("transport", "req-transport", "item/fileChange/requestApproval") in calls
    assert ("notify", "channels", "task-transport") not in calls


def test_build_interactive_sink_accepts_app_server_line_writer(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []

    class BaseSink:
        def __init__(self, name):
            self.name = name

        def notify(self, prompt):
            calls.append(("notify", self.name, prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", self.name, task_id))

    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink("claude"))
    monkeypatch.setattr(m, "_codex_channels_sink", BaseSink("channels"))

    composite = m._build_interactive_sink(
        app_server_line_writer=lambda line: calls.append(("line", line)),
    )
    composite.notify(
        m.create_interactive_prompt(
            task_id="task-line-writer",
            question="Approve?",
            options=["Yes"],
            method="item/fileChange/requestApproval",
            request_id="req-line-writer",
            params={"reason": "Need approval"},
        )
    )
    composite.clear("task-line-writer")

    assert (
        "line",
        '{"id": "req-line-writer", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n',
    ) in calls
    assert ("notify", "channels", "task-line-writer") not in calls


def test_build_interactive_sink_accepts_app_server_stream(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []

    class BaseSink:
        def __init__(self, name):
            self.name = name

        def notify(self, prompt):
            calls.append(("notify", self.name, prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", self.name, task_id))

    class Stream:
        def write(self, text):
            calls.append(("write", text))

        def flush(self):
            calls.append(("flush", ""))

    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink("claude"))
    monkeypatch.setattr(m, "_codex_channels_sink", BaseSink("channels"))

    composite = m._build_interactive_sink(
        app_server_stream=Stream(),
        app_server_stream_lock=m.threading.Lock(),
    )
    composite.notify(
        m.create_interactive_prompt(
            task_id="task-stream-writer",
            question="Approve?",
            options=["Yes"],
            method="item/fileChange/requestApproval",
            request_id="req-stream-writer",
            params={"reason": "Need approval"},
        )
    )
    composite.clear("task-stream-writer")

    assert (
        "write",
        '{"id": "req-stream-writer", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n',
    ) in calls
    assert ("flush", "") in calls
    assert ("notify", "channels", "task-stream-writer") not in calls


def test_build_interactive_sink_uses_attached_app_server_transport_by_default(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []

    class BaseSink:
        def __init__(self, name):
            self.name = name

        def notify(self, prompt):
            calls.append(("notify", self.name, prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", self.name, task_id))

    class Transport:
        def send_request(self, request):
            calls.append(("transport", request["id"], request["method"]))
            return request

    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink("claude"))
    monkeypatch.setattr(m, "_codex_channels_sink", BaseSink("channels"))
    monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: Transport())

    composite = m._build_interactive_sink()
    composite.notify(
        m.create_interactive_prompt(
            task_id="task-attached-transport",
            question="Approve?",
            options=["Yes"],
            method="item/fileChange/requestApproval",
            request_id="req-attached-transport",
            params={"reason": "Need approval"},
        )
    )
    composite.clear("task-attached-transport")

    assert ("transport", "req-attached-transport", "item/fileChange/requestApproval") in calls
    assert ("notify", "channels", "task-attached-transport") not in calls


def test_notify_channel_uses_attached_app_server_transport_by_default(monkeypatch):
    import hermit_agent.mcp_channel as m
    from hermit_agent.interactive_prompts import create_interactive_prompt as build_prompt

    calls = []

    class BaseSink:
        def __init__(self, name):
            self.name = name

        def notify(self, prompt):
            calls.append(("notify", self.name, prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", self.name, task_id))

    class Transport:
        def send_request(self, request):
            calls.append(("transport", request["id"], request["method"]))
            return request

    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink("claude"))
    monkeypatch.setattr(m, "_codex_channels_sink", BaseSink("channels"))
    monkeypatch.setattr(
        m,
        "_default_interactive_sink",
        m.compose_interactive_prompt_sinks(m._claude_mcp_sink, m._codex_channels_sink),
    )
    monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: Transport())
    monkeypatch.setattr(
        m,
        "create_interactive_prompt",
        lambda **kwargs: build_prompt(
            **{**kwargs, "method": "item/fileChange/requestApproval"},
            request_id="req-runtime-attached",
            params={"reason": "Need approval"},
        ),
    )

    m._notify_channel(
        "task-runtime-attached",
        "Approve?",
        ["Yes"],
        prompt_kind="waiting",
        tool_name="ask",
    )

    assert ("transport", "req-runtime-attached", "item/fileChange/requestApproval") in calls
    assert ("notify", "channels", "task-runtime-attached") not in calls


def test_notify_channel_end_to_end_posts_codex_channels_reply_via_gateway(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {"posts": []}

    class FakeSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction
            self._done = False

        def start(self):
            calls["session_started"] = True

        def poll_response(self):
            if self._done:
                return None
            self._done = True
            return "approved"

        def terminate(self):
            calls["terminated"] = calls.get("terminated", 0) + 1

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    class FakeResponse:
        def __init__(self, status_code=200):
            self.status_code = status_code

    def fake_post(url, payload=None, headers=None, timeout=None):
        calls["posts"].append(
            {"url": url, "json": payload, "headers": headers, "timeout": timeout}
        )
        return FakeResponse(200)

    monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: calls.setdefault("notification", (content, meta)))
    monkeypatch.setattr(
        m,
        "load_settings",
        lambda cwd=None: {
            "gateway_url": "http://gateway.test",
            "gateway_api_key": "token-123",
            "codex_channels": {"enabled": True},
        },
    )
    monkeypatch.setattr(m, "load_codex_channels_settings", lambda cfg, cwd: SimpleNamespace(enabled=True))
    monkeypatch.setattr(m, "CodexChannelsWaitSession", FakeSession)
    monkeypatch.setattr(m.threading, "Thread", FakeThread)
    monkeypatch.setattr(m.httpx, "post", lambda url, json=None, headers=None, timeout=None: fake_post(url, payload=json, headers=headers, timeout=timeout))

    try:
        m._remember_task_context("task-auto", "/tmp/project-c")
        m._notify_channel(
            "task-auto",
            "[Permission request] Continue?",
            ["Yes", "No"],
            prompt_kind="permission_ask",
            tool_name="bash",
        )
        assert calls["session_started"] is True
        assert calls["interaction"]["kind"] == "approval_request"
        assert calls["posts"] == [{
            "url": "http://gateway.test/tasks/task-auto/reply",
            "json": {"message": "approved"},
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer token-123",
            },
            "timeout": 10.0,
        }]
        assert calls["terminated"] == 1
        with m._codex_channel_waits_lock:
            assert "task-auto" not in m._codex_channel_waits
    finally:
        m._forget_task_context("task-auto")


def test_notify_channel_uses_active_session_send_request_for_permission_prompts(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {}

    class BaseSink:
        def notify(self, prompt):
            calls.setdefault("base_notified", []).append(prompt.task_id)

        def clear(self, task_id, *, expected=None):
            calls.setdefault("base_cleared", []).append(task_id)

    class FakeSession:
        async def send_request(self, request, result_type, **kwargs):
            calls["request"] = {"method": request.method, "params": request.params}
            return result_type.model_validate({"action": "accept", "content": {"answer": "Yes (once)"}})

    monkeypatch.setattr(
        m,
        "_default_interactive_sink",
        m.compose_interactive_prompt_sinks(BaseSink(), BaseSink()),
    )
    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink())
    monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: None)
    monkeypatch.setattr(m, "_gateway_reply", lambda task_id, answer: calls.setdefault("reply", (task_id, answer)) or True)

    loop, thread = _start_loop()
    try:
        m._set_active_session(FakeSession(), loop)
        m._notify_channel(
            "task-session-request",
            "[Permission request] bash\nprintf 'hi\\n'\n\nAllow?",
            ["Yes (once)", "No"],
            prompt_kind="permission_ask",
            tool_name="bash",
        )

        deadline = time.time() + 2
        while time.time() < deadline and "reply" not in calls:
            time.sleep(0.01)

        assert calls["request"]["method"] == "elicitation/create"
        assert "Hermit가 터미널 명령 실행 권한을 요청했어." in calls["request"]["params"].message
        assert "명령: printf 'hi\\n'" in calls["request"]["params"].message
        assert calls["reply"] == ("task-session-request", "Yes (once)")
    finally:
        _stop_loop(loop, thread)
        with m._session_lock:
            m._current_session = None
            m._current_loop = None


def test_notify_channel_uses_task_augmented_elicitation_when_supported(monkeypatch):
    import hermit_agent.mcp_channel as m
    import mcp.types as mcp_types

    calls = {}

    class BaseSink:
        def notify(self, prompt):
            calls.setdefault("base_notified", []).append(prompt.task_id)

        def clear(self, task_id, *, expected=None):
            calls.setdefault("base_cleared", []).append(task_id)

    class FakeExperimental:
        async def elicit_as_task(self, message, requested_schema, ttl=60000):
            calls["task_elicitation"] = {"message": message, "schema": requested_schema, "ttl": ttl}
            return mcp_types.ElicitResult(action="accept", content={"answer": "Yes (once)"})

    class FakeSession:
        client_params = type(
            "P",
            (),
            {
                "capabilities": mcp_types.ClientCapabilities(
                    tasks=mcp_types.ClientTasksCapability(
                        requests=mcp_types.ClientTasksRequestsCapability(
                            elicitation=mcp_types.TasksElicitationCapability(
                                create=mcp_types.TasksCreateElicitationCapability()
                            )
                        )
                    )
                )
            },
        )()

        experimental = FakeExperimental()

        async def send_request(self, request, result_type, **kwargs):
            raise AssertionError("plain send_request should not be used when task-augmented elicitation is supported")

    monkeypatch.setattr(
        m,
        "_default_interactive_sink",
        m.compose_interactive_prompt_sinks(BaseSink(), BaseSink()),
    )
    monkeypatch.setattr(m, "_claude_mcp_sink", BaseSink())
    monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: None)
    monkeypatch.setattr(m, "_gateway_reply", lambda task_id, answer: calls.setdefault("reply", (task_id, answer)) or True)

    loop, thread = _start_loop()
    try:
        m._set_active_session(FakeSession(), loop)
        m._notify_channel(
            "task-session-task-elicitation",
            "[Permission request] bash\nprintf 'hi\\n'\n\nAllow?",
            ["Yes (once)", "No"],
            prompt_kind="permission_ask",
            tool_name="bash",
        )

        deadline = time.time() + 2
        while time.time() < deadline and "reply" not in calls:
            time.sleep(0.01)

        assert calls["task_elicitation"]["message"].startswith("[Permission request] bash")
        assert calls["reply"] == ("task-session-task-elicitation", "Yes (once)")
    finally:
        _stop_loop(loop, thread)
        with m._session_lock:
            m._current_session = None
            m._current_loop = None


def test_notify_channel_can_disable_session_elicitation_via_env(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {}
    monkeypatch.setenv("HERMIT_DISABLE_CODEX_SESSION_ELICITATION", "1")

    class FakeCodexChannelsSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction

        def start(self):
            calls["session_started"] = True

        def terminate(self):
            calls["terminated"] = True

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            calls["thread_args"] = args

        def start(self):
            calls["thread_started"] = True

    class FakeServerSession:
        async def send_request(self, request, result_type, **kwargs):
            raise AssertionError("session elicitation should be disabled by env")

    monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: calls.setdefault("notification", (content, meta)))
    monkeypatch.setattr(m, "_notify_visible_prompt", lambda **kwargs: calls.setdefault("visible_prompt", kwargs))
    monkeypatch.setattr(m, "load_settings", lambda cwd=None: {"codex_channels": {"enabled": True}})
    monkeypatch.setattr(m, "load_codex_channels_settings", lambda cfg, cwd: SimpleNamespace(enabled=True))
    monkeypatch.setattr(m, "CodexChannelsWaitSession", FakeCodexChannelsSession)
    monkeypatch.setattr(m.threading, "Thread", FakeThread)
    monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: None)

    try:
        with m._session_lock:
            m._current_session = FakeServerSession()
            m._current_loop = object()
        m._notify_channel(
            "task-session-disabled",
            "Need input",
            ["A"],
            prompt_kind="waiting",
            tool_name="ask",
        )
        assert calls["session_started"] is True
        assert calls["thread_started"] is True
        assert calls["interaction"]["kind"] == "user_input_request"
    finally:
        with m._session_lock:
            m._current_session = None
            m._current_loop = None
        with m._codex_channel_waits_lock:
            m._codex_channel_waits.clear()


def test_notify_channel_falls_back_to_codex_channels_when_session_request_fails(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = {}

    class FakeCodexChannelsSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction

        def start(self):
            calls["session_started"] = True

        def terminate(self):
            calls["terminated"] = calls.get("terminated", 0) + 1

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            self._target = target
            self._args = args

        def start(self):
            calls["thread_started"] = True

    class FakeServerSession:
        async def send_request(self, request, result_type, **kwargs):
            raise RuntimeError("session transport failed")

    loop, thread = _start_loop()
    try:
        monkeypatch.setattr(m, "_fire_channel_notification_sync", lambda content, meta: calls.setdefault("notification", (content, meta)))
        monkeypatch.setattr(m, "_notify_visible_prompt", lambda **kwargs: calls.setdefault("visible_prompt", kwargs))
        monkeypatch.setattr(m, "load_settings", lambda cwd=None: {"codex_channels": {"enabled": True}})
        monkeypatch.setattr(m, "load_codex_channels_settings", lambda cfg, cwd: SimpleNamespace(enabled=True))
        monkeypatch.setattr(m, "CodexChannelsWaitSession", FakeCodexChannelsSession)
        monkeypatch.setattr(m.threading, "Thread", FakeThread)
        monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: None)
        m._set_active_session(FakeServerSession(), loop)
        m._notify_channel(
            "task-session-fallback",
            "Need input",
            ["A"],
            prompt_kind="waiting",
            tool_name="ask",
        )

        deadline = time.time() + 2
        while time.time() < deadline and "session_started" not in calls:
            time.sleep(0.01)

        assert calls["session_started"] is True
        assert calls["thread_started"] is True
        assert calls["interaction"]["kind"] == "user_input_request"
    finally:
        _stop_loop(loop, thread)
        with m._session_lock:
            m._current_session = None
            m._current_loop = None
        with m._codex_channel_waits_lock:
            m._codex_channel_waits.clear()


def test_notify_visible_prompt_dedupes_repeated_messages(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []
    monkeypatch.setattr(m.os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    with m._visible_prompt_notifications_lock:
        m._visible_prompt_notifications.clear()

    m._notify_visible_prompt(
        task_id="task-visible",
        question="[Permission request] bash\npwd\n\nAllow?",
        options=["Yes (once)", "No"],
        prompt_kind="permission_ask",
    )
    m._notify_visible_prompt(
        task_id="task-visible",
        question="[Permission request] bash\npwd\n\nAllow?",
        options=["Yes (once)", "No"],
        prompt_kind="permission_ask",
    )

    assert len(calls) == 1
    m._clear_visible_prompt_notification("task-visible")


def test_notify_channel_skips_local_visible_prompt_when_attached_transport_exists(monkeypatch):
    import hermit_agent.mcp_channel as m

    calls = []

    class Transport:
        def send_request(self, request):
            calls.append(("transport", request["id"], request["method"]))
            return request

    monkeypatch.setattr(m, "get_attached_codex_app_server_transport", lambda: Transport())
    monkeypatch.setattr(m, "_notify_visible_prompt", lambda **kwargs: calls.append(("visible", kwargs["task_id"])))

    from hermit_agent.interactive_prompts import create_interactive_prompt as build_prompt

    monkeypatch.setattr(
        m,
        "create_interactive_prompt",
        lambda **kwargs: build_prompt(
            **{**kwargs, "method": "item/fileChange/requestApproval"},
            request_id="req-visible-skip",
            params={"reason": "Need approval"},
        ),
    )

    m._notify_channel("task-visible-skip", "Approve?", ["Yes"], prompt_kind="waiting", tool_name="ask")

    assert ("visible", "task-visible-skip") not in calls
    assert ("transport", "req-visible-skip", "item/fileChange/requestApproval") in calls


def test_build_session_elicitation_request_localizes_common_waiting_question():
    import hermit_agent.mcp_channel as m

    prompt = m.create_interactive_prompt(
        task_id="task-localized",
        question="Which environment should we use?",
        options=[],
        prompt_kind="waiting",
    )

    request = m._build_session_elicitation_request(prompt)

    assert request.params.message == "어느 환경으로 진행할까요?"
