from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from ..interactive_prompts import InteractivePrompt, build_codex_app_server_request
from .composite import CompositeInteractivePromptSink, compose_interactive_prompt_sinks
from .codex_transport import resolve_codex_app_server_transport
from .protocols import CodexAppServerTransport, InteractivePromptSink


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
