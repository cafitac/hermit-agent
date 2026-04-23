from __future__ import annotations

import threading
from types import SimpleNamespace

from hermit_agent.interactive_prompts import create_interactive_prompt
from hermit_agent.interactive_sinks import (
    BufferedCodexAppServerTransport,
    CallbackCodexAppServerTransport,
    ClaudeMcpInteractiveSink,
    CodexAppServerInteractiveSink,
    CodexChannelsInteractiveSink,
    CompositeInteractivePromptSink,
    JsonRpcLineCodexAppServerTransport,
    StreamJsonRpcCodexAppServerTransport,
    build_codex_app_server_sink,
    compose_interactive_prompt_sinks,
    maybe_start_codex_channels_wait_session,
    serialize_codex_app_server_request,
    write_codex_app_server_message,
)


def test_claude_mcp_sink_emits_channel_notification_meta():
    calls = {}
    sink = ClaudeMcpInteractiveSink(
        notify=lambda content, meta: calls.setdefault("notification", (content, meta)),
    )

    prompt = create_interactive_prompt(
        task_id="task-1",
        question="Continue?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
    )
    sink.notify(prompt)

    assert calls["notification"] == (
        "Continue?",
        {
            "task_id": "task-1",
            "kind": "waiting",
            "options": "Yes,No",
            "prompt_kind": "permission_ask",
            "tool_name": "bash",
        },
    )


def test_composite_sink_fans_out_and_clear_calls_all_children():
    calls: list[tuple[str, str]] = []

    class Sink:
        def notify(self, prompt):
            calls.append(("notify", prompt.task_id))

        def clear(self, task_id, *, expected=None):
            calls.append(("clear", task_id))

    composite = CompositeInteractivePromptSink(Sink(), Sink())
    prompt = create_interactive_prompt(task_id="task-2", question="Q", options=[])

    composite.notify(prompt)
    composite.clear("task-2")

    assert calls == [
        ("notify", "task-2"),
        ("notify", "task-2"),
        ("clear", "task-2"),
        ("clear", "task-2"),
    ]


def test_maybe_start_codex_channels_wait_session_returns_started_session():
    calls = {}

    class FakeSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction

        def start(self):
            calls["started"] = True

    prompt = create_interactive_prompt(
        task_id="task-3",
        question="Need input",
        options=["A"],
    )

    session = maybe_start_codex_channels_wait_session(
        prompt,
        settings=SimpleNamespace(enabled=True),
        session_factory=FakeSession,
        interaction_builder=lambda item: {"id": item.task_id},
    )

    assert isinstance(session, FakeSession)
    assert calls == {"interaction": {"id": "task-3"}, "started": True}


def test_codex_app_server_sink_emits_request_and_tracks_pending():
    transport = BufferedCodexAppServerTransport()
    sink = CodexAppServerInteractiveSink(transport=transport)

    prompt = create_interactive_prompt(
        task_id="task-app",
        question="Approve?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
        method="item/commandExecution/requestApproval",
        request_id="req-app",
        thread_id="thread-app",
        turn_id="turn-app",
        params={"command": "pwd"},
    )

    sink.notify(prompt)

    assert transport.requests == [{
        "id": "req-app",
        "method": "item/commandExecution/requestApproval",
        "params": {
            "command": "pwd",
            "threadId": "thread-app",
            "turnId": "turn-app",
        },
    }]
    assert sink.pending_requests["task-app"]["id"] == "req-app"
    sink.clear("task-app")
    assert sink.pending_requests == {}


def test_build_codex_app_server_sink_wraps_request_sender_callback():
    calls = {}

    sink = build_codex_app_server_sink(
        request_sender=lambda request: calls.setdefault("request", request),
    )

    assert sink is not None
    prompt = create_interactive_prompt(
        task_id="task-build",
        question="Approve?",
        options=["Yes"],
        method="item/fileChange/requestApproval",
        request_id="req-build",
        params={"reason": "Need approval"},
    )
    sink.notify(prompt)

    assert calls["request"] == {
        "id": "req-build",
        "method": "item/fileChange/requestApproval",
        "params": {"reason": "Need approval"},
    }


def test_callback_transport_forwards_request():
    calls = {}
    transport = CallbackCodexAppServerTransport(
        request_sender=lambda request: calls.setdefault("request", request),
    )

    request = {"id": "req-raw", "method": "item/tool/requestUserInput", "params": {}}
    assert transport.send_request(request) == request
    assert calls["request"] == request


def test_serialize_codex_app_server_request_appends_newline():
    request = {"id": "req-json", "method": "item/tool/requestUserInput", "params": {"a": 1}}
    assert serialize_codex_app_server_request(request) == (
        '{"id": "req-json", "method": "item/tool/requestUserInput", "params": {"a": 1}}\n'
    )


def test_json_rpc_line_transport_writes_serialized_message():
    calls = {}
    transport = JsonRpcLineCodexAppServerTransport(
        line_writer=lambda line: calls.setdefault("line", line),
    )

    request = {"id": "req-line", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}
    assert transport.send_request(request) == (
        '{"id": "req-line", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n'
    )
    assert calls["line"] == (
        '{"id": "req-line", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n'
    )


def test_build_codex_app_server_sink_accepts_line_writer():
    calls = {}

    sink = build_codex_app_server_sink(
        line_writer=lambda line: calls.setdefault("line", line),
    )

    assert sink is not None
    prompt = create_interactive_prompt(
        task_id="task-line",
        question="Approve?",
        options=["Yes"],
        method="item/fileChange/requestApproval",
        request_id="req-line",
        params={"reason": "Need approval"},
    )
    sink.notify(prompt)

    assert calls["line"] == (
        '{"id": "req-line", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n'
    )


def test_write_codex_app_server_message_writes_and_flushes_once():
    events: list[tuple[str, str]] = []

    class Stream:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    write_codex_app_server_message(
        Stream(),
        {"id": "req-stream", "method": "item/tool/requestUserInput", "params": {}},
    )

    assert events == [
        ("write", '{"id": "req-stream", "method": "item/tool/requestUserInput", "params": {}}\n'),
        ("flush", ""),
    ]


def test_stream_json_rpc_transport_writes_to_stream_with_lock():
    events: list[tuple[str, str]] = []

    class Stream:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    transport = StreamJsonRpcCodexAppServerTransport(
        stream=Stream(),
        lock=threading.Lock(),
    )

    transport.send_request(
        {"id": "req-stream-transport", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}
    )

    assert events == [
        ("write", '{"id": "req-stream-transport", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n'),
        ("flush", ""),
    ]


def test_build_codex_app_server_sink_accepts_stream():
    events: list[tuple[str, str]] = []

    class Stream:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    sink = build_codex_app_server_sink(
        stream=Stream(),
        stream_lock=threading.Lock(),
    )

    assert sink is not None
    prompt = create_interactive_prompt(
        task_id="task-stream",
        question="Approve?",
        options=["Yes"],
        method="item/fileChange/requestApproval",
        request_id="req-stream",
        params={"reason": "Need approval"},
    )
    sink.notify(prompt)

    assert events == [
        ("write", '{"id": "req-stream", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n'),
        ("flush", ""),
    ]


def test_compose_interactive_prompt_sinks_accepts_optional_sink():
    calls: list[str] = []

    class Sink:
        def __init__(self, name: str):
            self.name = name

        def notify(self, prompt):
            calls.append(f"notify:{self.name}:{prompt.task_id}")

        def clear(self, task_id, *, expected=None):
            calls.append(f"clear:{self.name}:{task_id}")

    composite = compose_interactive_prompt_sinks(Sink("base"), optional_sink=Sink("optional"))
    prompt = create_interactive_prompt(task_id="task-compose", question="Q", options=[])

    composite.notify(prompt)
    composite.clear("task-compose")

    assert calls == [
        "notify:base:task-compose",
        "notify:optional:task-compose",
        "clear:base:task-compose",
        "clear:optional:task-compose",
    ]


def test_codex_channels_sink_starts_session_bridges_reply_and_clears():
    calls = {"replies": []}

    class FakeSession:
        def __init__(self, *, settings, interaction):
            calls["interaction"] = interaction
            self._done = False

        def start(self):
            calls["started"] = True

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

    sink = CodexChannelsInteractiveSink(
        settings_loader=lambda prompt: SimpleNamespace(enabled=True, task_id=prompt.task_id),
        session_factory=FakeSession,
        interaction_builder=lambda prompt: {"id": prompt.task_id},
        reply_callback=lambda prompt, answer: calls["replies"].append((prompt.task_id, answer)),
        thread_factory=FakeThread,
    )

    prompt = create_interactive_prompt(
        task_id="task-4",
        question="Approve?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
    )
    sink.notify(prompt)

    assert calls["interaction"] == {"id": "task-4"}
    assert calls["started"] is True
    assert calls["replies"] == [("task-4", "approved")]
    assert calls["terminated"] == 1
    assert sink.sessions == {}
