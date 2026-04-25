from __future__ import annotations

import os
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .interaction_contract import extract_answer_from_codex_result
from ..interactive_prompts import InteractivePrompt, build_codex_app_server_request
from ..interactive_sinks import (
    CodexAppServerTransport,
    JsonRpcLineCodexAppServerTransport,
    StreamJsonRpcCodexAppServerTransport,
)

_lock = threading.Lock()
_attached_transport: CodexAppServerTransport | None = None
ENV_CODEX_APP_SERVER_WRITER_FD = "HERMIT_CODEX_APP_SERVER_WRITER_FD"
ENV_CODEX_APP_SERVER_WRITER_PATH = "HERMIT_CODEX_APP_SERVER_WRITER_PATH"
ENV_CODEX_APP_SERVER_WRITER_ENCODING = "HERMIT_CODEX_APP_SERVER_WRITER_ENCODING"
ENV_CODEX_APP_SERVER_RESPONSE_MODE = "HERMIT_CODEX_APP_SERVER_RESPONSE_MODE"


@dataclass
class CodexAppServerAttachmentHandle:
    transport: CodexAppServerTransport
    previous_transport: CodexAppServerTransport | None
    cleanup: Any | None = None
    _closed: bool = False

    def close(self) -> CodexAppServerTransport | None:
        if self._closed:
            return get_attached_codex_app_server_transport()
        self._closed = True
        restored = swap_codex_app_server_transport(self.previous_transport)
        if self.cleanup is not None:
            self.cleanup()
        return restored


def attach_codex_app_server_transport(transport: CodexAppServerTransport) -> CodexAppServerTransport:
    global _attached_transport
    with _lock:
        _attached_transport = transport
    return transport


def swap_codex_app_server_transport(
    transport: CodexAppServerTransport | None,
) -> CodexAppServerTransport | None:
    global _attached_transport
    with _lock:
        previous = _attached_transport
        _attached_transport = transport
    return previous


def attach_codex_app_server_stream(
    stream: Any,
    *,
    stream_lock: threading.Lock | None = None,
) -> CodexAppServerTransport:
    transport = StreamJsonRpcCodexAppServerTransport(stream=stream, lock=stream_lock)
    return attach_codex_app_server_transport(transport)


def attach_codex_app_server_line_writer(line_writer) -> CodexAppServerTransport:
    transport = JsonRpcLineCodexAppServerTransport(line_writer=line_writer)
    return attach_codex_app_server_transport(transport)


def _open_codex_app_server_fd_stream(
    fd: int,
    *,
    encoding: str = "utf-8",
) -> Any:
    owned_fd = os.dup(fd)
    return os.fdopen(owned_fd, "w", buffering=1, encoding=encoding)


def _open_codex_app_server_path_stream(
    path: str,
    *,
    encoding: str = "utf-8",
) -> Any:
    return Path(path).open("w", buffering=1, encoding=encoding)


def get_attached_codex_app_server_transport() -> CodexAppServerTransport | None:
    with _lock:
        return _attached_transport


def has_attached_codex_app_server_transport() -> bool:
    return get_attached_codex_app_server_transport() is not None


def detach_codex_app_server_transport() -> CodexAppServerTransport | None:
    return swap_codex_app_server_transport(None)


@contextmanager
def attached_codex_app_server_transport(
    transport: CodexAppServerTransport,
) -> Iterator[CodexAppServerTransport]:
    previous = swap_codex_app_server_transport(transport)
    try:
        yield transport
    finally:
        swap_codex_app_server_transport(previous)


@contextmanager
def attached_codex_app_server_stream(
    stream: Any,
    *,
    stream_lock: threading.Lock | None = None,
) -> Iterator[CodexAppServerTransport]:
    transport = StreamJsonRpcCodexAppServerTransport(stream=stream, lock=stream_lock)
    with attached_codex_app_server_transport(transport):
        yield transport


@contextmanager
def attached_codex_app_server_line_writer(line_writer) -> Iterator[CodexAppServerTransport]:
    transport = JsonRpcLineCodexAppServerTransport(line_writer=line_writer)
    with attached_codex_app_server_transport(transport):
        yield transport


@contextmanager
def attached_codex_app_server_fd(
    fd: int,
    *,
    stream_lock: threading.Lock | None = None,
    encoding: str = "utf-8",
) -> Iterator[CodexAppServerTransport]:
    stream = _open_codex_app_server_fd_stream(fd, encoding=encoding)
    try:
        with attached_codex_app_server_stream(stream, stream_lock=stream_lock) as transport:
            yield transport
    finally:
        stream.close()


@contextmanager
def attached_codex_app_server_path(
    path: str,
    *,
    stream_lock: threading.Lock | None = None,
    encoding: str = "utf-8",
) -> Iterator[CodexAppServerTransport]:
    stream = _open_codex_app_server_path_stream(path, encoding=encoding)
    try:
        with attached_codex_app_server_stream(stream, stream_lock=stream_lock) as transport:
            yield transport
    finally:
        stream.close()


def bootstrap_codex_app_server_transport(
    transport: CodexAppServerTransport,
    *,
    cleanup: Any | None = None,
) -> CodexAppServerAttachmentHandle:
    previous = swap_codex_app_server_transport(transport)
    return CodexAppServerAttachmentHandle(
        transport=transport,
        previous_transport=previous,
        cleanup=cleanup,
    )


def bootstrap_codex_app_server_stream(
    stream: Any,
    *,
    stream_lock: threading.Lock | None = None,
) -> CodexAppServerAttachmentHandle:
    transport = StreamJsonRpcCodexAppServerTransport(stream=stream, lock=stream_lock)
    return bootstrap_codex_app_server_transport(transport)


def bootstrap_codex_app_server_line_writer(line_writer) -> CodexAppServerAttachmentHandle:
    transport = JsonRpcLineCodexAppServerTransport(line_writer=line_writer)
    return bootstrap_codex_app_server_transport(transport)


def bootstrap_codex_app_server_fd(
    fd: int,
    *,
    stream_lock: threading.Lock | None = None,
    encoding: str = "utf-8",
) -> CodexAppServerAttachmentHandle:
    stream = _open_codex_app_server_fd_stream(fd, encoding=encoding)
    transport = StreamJsonRpcCodexAppServerTransport(stream=stream, lock=stream_lock)
    return bootstrap_codex_app_server_transport(transport, cleanup=stream.close)


def bootstrap_codex_app_server_path(
    path: str,
    *,
    stream_lock: threading.Lock | None = None,
    encoding: str = "utf-8",
) -> CodexAppServerAttachmentHandle:
    stream = _open_codex_app_server_path_stream(path, encoding=encoding)
    transport = StreamJsonRpcCodexAppServerTransport(stream=stream, lock=stream_lock)
    return bootstrap_codex_app_server_transport(transport, cleanup=stream.close)


def bootstrap_codex_app_server_from_env(
    *,
    env: dict[str, str] | None = None,
    stream_lock: threading.Lock | None = None,
    log_fn=None,
) -> CodexAppServerAttachmentHandle | None:
    source = os.environ if env is None else env
    raw_fd = str(source.get(ENV_CODEX_APP_SERVER_WRITER_FD, "")).strip()
    raw_path = str(source.get(ENV_CODEX_APP_SERVER_WRITER_PATH, "")).strip()
    encoding = str(source.get(ENV_CODEX_APP_SERVER_WRITER_ENCODING, "utf-8")).strip() or "utf-8"
    log = log_fn or (lambda _line: None)

    if raw_fd:
        try:
            fd = int(raw_fd)
        except ValueError:
            log(f"[codex-app-server] invalid writer fd: {raw_fd}")
            return None
        try:
            handle = bootstrap_codex_app_server_fd(fd, stream_lock=stream_lock, encoding=encoding)
            log(f"[codex-app-server] attached writer fd {fd}")
            return handle
        except Exception as exc:
            log(f"[codex-app-server] failed to attach writer fd {fd}: {exc}")
            return None

    if raw_path:
        try:
            handle = bootstrap_codex_app_server_path(raw_path, stream_lock=stream_lock, encoding=encoding)
            log(f"[codex-app-server] attached writer path {raw_path}")
            return handle
        except Exception as exc:
            log(f"[codex-app-server] failed to attach writer path {raw_path}: {exc}")
            return None

    return None


def is_attached_codex_app_server_roundtrip_enabled(
    *,
    env: dict[str, str] | None = None,
) -> bool:
    source = os.environ if env is None else env
    return (
        get_attached_codex_app_server_transport() is not None
        and str(source.get(ENV_CODEX_APP_SERVER_RESPONSE_MODE, "")).strip().lower() == "stdin"
    )


def _extract_answer_from_codex_result(prompt: InteractivePrompt, result: dict[str, Any]) -> str:
    return extract_answer_from_codex_result(method=prompt.method, result=result)


def await_attached_codex_app_server_response(
    prompt: InteractivePrompt,
    *,
    env: dict[str, str] | None = None,
    input_stream: Any | None = None,
) -> str | None:
    if not is_attached_codex_app_server_roundtrip_enabled(env=env):
        return None
    transport = get_attached_codex_app_server_transport()
    if transport is None:
        return None
    request = build_codex_app_server_request(prompt)
    if request is None:
        return None
    transport.send_request(request)
    stream = input_stream or os.fdopen(os.dup(0), "r", encoding="utf-8", buffering=1)
    owns_stream = input_stream is None
    try:
        line = stream.readline()
    finally:
        if owns_stream:
            stream.close()
    if not line:
        raise RuntimeError("No response received from attached Codex app-server bridge.")
    payload = json.loads(line)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Attached Codex app-server bridge returned an invalid response payload.")
    return _extract_answer_from_codex_result(prompt, result)
