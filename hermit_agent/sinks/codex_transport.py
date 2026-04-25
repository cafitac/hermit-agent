from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from .protocols import CodexAppServerTransport


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


class CallbackCodexAppServerTransport:
    def __init__(self, *, request_sender: Callable[[dict[str, Any]], object]) -> None:
        self._request_sender = request_sender

    def send_request(self, request: dict[str, Any]) -> object:
        return self._request_sender(request)


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
        return StreamJsonRpcCodexAppServerTransport(stream=stream, lock=stream_lock)
    return None
