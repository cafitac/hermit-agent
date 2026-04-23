from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any, Protocol

from .interactive_prompts import InteractivePrompt, build_codex_app_server_request


class InteractivePromptSink(Protocol):
    def notify(self, prompt: InteractivePrompt) -> None: ...

    def clear(self, task_id: str, *, expected: Any | None = None) -> None: ...


class CodexAppServerTransport(Protocol):
    def send_request(self, request: dict[str, Any]) -> object: ...


class CompositeInteractivePromptSink:
    def __init__(self, *sinks: InteractivePromptSink) -> None:
        self._sinks = sinks

    def notify(self, prompt: InteractivePrompt) -> None:
        for sink in self._sinks:
            sink.notify(prompt)

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        for sink in self._sinks:
            sink.clear(task_id, expected=expected)


def compose_interactive_prompt_sinks(
    *base_sinks: InteractivePromptSink,
    optional_sink: InteractivePromptSink | None = None,
) -> CompositeInteractivePromptSink:
    sinks = [*base_sinks]
    if optional_sink is not None:
        sinks.append(optional_sink)
    return CompositeInteractivePromptSink(*sinks)


class ClaudeMcpInteractiveSink:
    def __init__(self, *, notify: Callable[[str, dict[str, str]], None]) -> None:
        self._notify = notify

    def notify(self, prompt: InteractivePrompt) -> None:
        from .interactive_prompts import channel_notification_meta

        self._notify(prompt.question, channel_notification_meta(prompt))

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        return None


class CallbackCodexAppServerTransport:
    def __init__(self, *, request_sender: Callable[[dict[str, Any]], object]) -> None:
        self._request_sender = request_sender

    def send_request(self, request: dict[str, Any]) -> object:
        return self._request_sender(request)


def serialize_codex_app_server_message(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False) + "\n"


def serialize_codex_app_server_request(request: dict[str, Any]) -> str:
    return serialize_codex_app_server_message(request)


def write_codex_app_server_message(
    stream: Any,
    message: dict[str, Any],
    *,
    lock: threading.Lock | None = None,
) -> None:
    manager = lock if lock is not None else nullcontext()
    with manager:
        stream.write(serialize_codex_app_server_message(message))
        stream.flush()


class JsonRpcLineCodexAppServerTransport:
    def __init__(self, *, line_writer: Callable[[str], object]) -> None:
        self._line_writer = line_writer

    def send_request(self, request: dict[str, Any]) -> object:
        message = serialize_codex_app_server_request(request)
        return self._line_writer(message)


class StreamJsonRpcCodexAppServerTransport:
    def __init__(
        self,
        *,
        stream: Any,
        lock: threading.Lock | None = None,
    ) -> None:
        self._stream = stream
        self._lock = lock

    def send_request(self, request: dict[str, Any]) -> None:
        write_codex_app_server_message(self._stream, request, lock=self._lock)


class BufferedCodexAppServerTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return request


def resolve_codex_app_server_transport(
    *,
    transport: CodexAppServerTransport | None = None,
    request_sender: Callable[[dict[str, Any]], object] | None = None,
    line_writer: Callable[[str], object] | None = None,
    stream: Any | None = None,
    stream_lock: threading.Lock | None = None,
) -> CodexAppServerTransport | None:
    if transport is not None:
        return transport
    if request_sender is not None:
        return CallbackCodexAppServerTransport(request_sender=request_sender)
    if line_writer is not None:
        return JsonRpcLineCodexAppServerTransport(line_writer=line_writer)
    if stream is not None:
        return StreamJsonRpcCodexAppServerTransport(
            stream=stream,
            lock=stream_lock,
        )
    return None


class CodexAppServerInteractiveSink:
    def __init__(
        self,
        *,
        transport: CodexAppServerTransport,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._transport = transport
        self._log = log_fn or (lambda _line: None)
        self.pending_requests: dict[str, dict[str, Any]] = {}

    def notify(self, prompt: InteractivePrompt) -> None:
        request = build_codex_app_server_request(prompt)
        if request is None:
            return
        self.pending_requests[prompt.task_id] = request
        self._transport.send_request(request)
        self._log(
            f"[codex-app-server] request sent task={prompt.task_id[:8]} "
            f"method={request['method']}"
        )

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        self.pending_requests.pop(task_id, None)


def build_codex_app_server_sink(
    *,
    transport: CodexAppServerTransport | None = None,
    request_sender: Callable[[dict[str, Any]], object] | None = None,
    line_writer: Callable[[str], object] | None = None,
    stream: Any | None = None,
    stream_lock: threading.Lock | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> CodexAppServerInteractiveSink | None:
    resolved_transport = resolve_codex_app_server_transport(
        transport=transport,
        request_sender=request_sender,
        line_writer=line_writer,
        stream=stream,
        stream_lock=stream_lock,
    )
    if resolved_transport is None:
        return None
    return CodexAppServerInteractiveSink(transport=resolved_transport, log_fn=log_fn)


def build_composed_interactive_sink(
    *,
    claude_sink: InteractivePromptSink,
    codex_channels_sink: InteractivePromptSink,
    app_server_sink: InteractivePromptSink | None = None,
    transport: CodexAppServerTransport | None = None,
    request_sender: Callable[[dict[str, Any]], object] | None = None,
    line_writer: Callable[[str], object] | None = None,
    stream: Any | None = None,
    stream_lock: threading.Lock | None = None,
    log_fn: Callable[[str], None] | None = None,
    include_codex_channels: bool | None = None,
) -> CompositeInteractivePromptSink:
    resolved_app_server_sink = app_server_sink or build_codex_app_server_sink(
        transport=transport,
        request_sender=request_sender,
        line_writer=line_writer,
        stream=stream,
        stream_lock=stream_lock,
        log_fn=log_fn,
    )
    resolved_include_codex_channels = (
        resolved_app_server_sink is None
        if include_codex_channels is None
        else include_codex_channels
    )
    sinks: list[InteractivePromptSink] = [claude_sink]
    if resolved_include_codex_channels:
        sinks.append(codex_channels_sink)
    return compose_interactive_prompt_sinks(
        *sinks,
        optional_sink=resolved_app_server_sink,
    )


def maybe_start_codex_channels_wait_session(
    prompt: InteractivePrompt,
    *,
    settings: Any,
    session_factory: Callable[..., Any],
    interaction_builder: Callable[[InteractivePrompt], dict[str, Any]],
) -> Any | None:
    if not getattr(settings, "enabled", False):
        return None

    try:
        session = session_factory(
            settings=settings,
            interaction=interaction_builder(prompt),
        )
        session.start()
        return session
    except Exception:
        return None


class CodexChannelsInteractiveSink:
    def __init__(
        self,
        *,
        settings_loader: Callable[[InteractivePrompt], Any],
        session_factory: Callable[..., Any],
        interaction_builder: Callable[[InteractivePrompt], dict[str, Any]],
        reply_callback: Callable[[InteractivePrompt, str], object],
        thread_factory: Callable[..., Any] = threading.Thread,
        sleep_fn: Callable[[float], None] = time.sleep,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._settings_loader = settings_loader
        self._session_factory = session_factory
        self._interaction_builder = interaction_builder
        self._reply_callback = reply_callback
        self._thread_factory = thread_factory
        self._sleep_fn = sleep_fn
        self._log = log_fn or (lambda _line: None)
        self.sessions: dict[str, Any] = {}
        self.lock = threading.Lock()

    def notify(self, prompt: InteractivePrompt) -> None:
        settings = self._settings_loader(prompt)
        session = maybe_start_codex_channels_wait_session(
            prompt,
            settings=settings,
            session_factory=self._session_factory,
            interaction_builder=self._interaction_builder,
        )
        if session is None:
            return

        self.clear(prompt.task_id)
        with self.lock:
            self.sessions[prompt.task_id] = session

        thread = self._thread_factory(
            target=self._bridge_reply,
            args=(prompt, session),
            name=f"codex-channels-mcp-{prompt.task_id[:8]}",
            daemon=True,
        )
        thread.start()
        self._log(f"[codex-channels] wait started task={prompt.task_id[:8]}")

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        with self.lock:
            session = self.sessions.get(task_id)
            if session is None:
                return
            if expected is not None and session is not expected:
                return
            self.sessions.pop(task_id, None)
        try:
            session.terminate()
        except Exception as exc:
            self._log(f"[codex-channels] terminate error task={task_id[:8]} err={exc}")

    def _bridge_reply(self, prompt: InteractivePrompt, session: Any, *, poll_interval: float = 0.25) -> None:
        try:
            while True:
                with self.lock:
                    active = self.sessions.get(prompt.task_id)
                if active is not session:
                    return
                answer = session.poll_response()
                if answer is not None:
                    self._reply_callback(prompt, str(answer))
                    return
                self._sleep_fn(poll_interval)
        finally:
            self.clear(prompt.task_id, expected=session)
