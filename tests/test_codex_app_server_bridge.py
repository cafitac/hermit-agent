from __future__ import annotations

import os
import tempfile
import threading

from hermit_agent.codex_app_server_bridge import (
    ENV_CODEX_APP_SERVER_WRITER_ENCODING,
    ENV_CODEX_APP_SERVER_WRITER_FD,
    ENV_CODEX_APP_SERVER_WRITER_PATH,
    attached_codex_app_server_fd,
    attach_codex_app_server_stream,
    attached_codex_app_server_path,
    attach_codex_app_server_line_writer,
    attach_codex_app_server_transport,
    attached_codex_app_server_stream,
    attached_codex_app_server_line_writer,
    attached_codex_app_server_transport,
    bootstrap_codex_app_server_fd,
    bootstrap_codex_app_server_from_env,
    bootstrap_codex_app_server_line_writer,
    bootstrap_codex_app_server_path,
    bootstrap_codex_app_server_stream,
    bootstrap_codex_app_server_transport,
    detach_codex_app_server_transport,
    get_attached_codex_app_server_transport,
    has_attached_codex_app_server_transport,
    swap_codex_app_server_transport,
)
from hermit_agent.interactive_sinks import BufferedCodexAppServerTransport


def test_attach_and_detach_codex_app_server_transport():
    try:
        transport = BufferedCodexAppServerTransport()
        attach_codex_app_server_transport(transport)
        assert get_attached_codex_app_server_transport() is transport
    finally:
        detached = detach_codex_app_server_transport()
        assert detached is transport
        assert get_attached_codex_app_server_transport() is None


def test_attach_codex_app_server_stream_builds_transport_that_writes():
    events: list[tuple[str, str]] = []

    class Stream:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    try:
        transport = attach_codex_app_server_stream(Stream(), stream_lock=threading.Lock())
        transport.send_request(
            {"id": "req-bridge", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}
        )
        assert events == [
            ("write", '{"id": "req-bridge", "method": "item/fileChange/requestApproval", "params": {"reason": "Need approval"}}\n'),
            ("flush", ""),
        ]
    finally:
        detach_codex_app_server_transport()


def test_attached_codex_app_server_transport_context_restores_previous():
    original = BufferedCodexAppServerTransport()
    nested = BufferedCodexAppServerTransport()
    attach_codex_app_server_transport(original)
    try:
        with attached_codex_app_server_transport(nested):
            assert get_attached_codex_app_server_transport() is nested
            assert has_attached_codex_app_server_transport() is True
        assert get_attached_codex_app_server_transport() is original
    finally:
        detach_codex_app_server_transport()
        assert has_attached_codex_app_server_transport() is False


def test_attached_codex_app_server_stream_context_restores_previous():
    original = BufferedCodexAppServerTransport()
    events: list[tuple[str, str]] = []

    class Stream:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    attach_codex_app_server_transport(original)
    try:
        with attached_codex_app_server_stream(Stream(), stream_lock=threading.Lock()) as transport:
            assert get_attached_codex_app_server_transport() is transport
            transport.send_request(
                {"id": "req-nested", "method": "item/tool/requestUserInput", "params": {}}
            )
        assert get_attached_codex_app_server_transport() is original
        assert events == [
            ("write", '{"id": "req-nested", "method": "item/tool/requestUserInput", "params": {}}\n'),
            ("flush", ""),
        ]
    finally:
        detach_codex_app_server_transport()


def test_swap_codex_app_server_transport_returns_previous():
    first = BufferedCodexAppServerTransport()
    second = BufferedCodexAppServerTransport()
    attach_codex_app_server_transport(first)
    try:
        previous = swap_codex_app_server_transport(second)
        assert previous is first
        assert get_attached_codex_app_server_transport() is second
    finally:
        detach_codex_app_server_transport()


def test_attach_codex_app_server_line_writer_builds_transport_that_writes():
    events: list[tuple[str, str]] = []

    try:
        transport = attach_codex_app_server_line_writer(lambda line: events.append(("line", line)))
        transport.send_request(
            {"id": "req-line-bridge", "method": "item/tool/requestUserInput", "params": {}}
        )
        assert events == [
            ("line", '{"id": "req-line-bridge", "method": "item/tool/requestUserInput", "params": {}}\n'),
        ]
    finally:
        detach_codex_app_server_transport()


def test_attached_codex_app_server_line_writer_context_restores_previous():
    original = BufferedCodexAppServerTransport()
    events: list[tuple[str, str]] = []

    attach_codex_app_server_transport(original)
    try:
        with attached_codex_app_server_line_writer(lambda line: events.append(("line", line))) as transport:
            assert get_attached_codex_app_server_transport() is transport
            transport.send_request(
                {"id": "req-line-nested", "method": "item/tool/requestUserInput", "params": {}}
            )
        assert get_attached_codex_app_server_transport() is original
        assert events == [
            ("line", '{"id": "req-line-nested", "method": "item/tool/requestUserInput", "params": {}}\n'),
        ]
    finally:
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_transport_returns_closeable_handle():
    original = BufferedCodexAppServerTransport()
    nested = BufferedCodexAppServerTransport()
    attach_codex_app_server_transport(original)
    try:
        handle = bootstrap_codex_app_server_transport(nested)
        assert get_attached_codex_app_server_transport() is nested
        handle.close()
        assert get_attached_codex_app_server_transport() is original
        handle.close()
        assert get_attached_codex_app_server_transport() is original
    finally:
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_stream_returns_closeable_handle():
    original = BufferedCodexAppServerTransport()
    events: list[tuple[str, str]] = []

    class Stream:
        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", ""))

    attach_codex_app_server_transport(original)
    try:
        handle = bootstrap_codex_app_server_stream(Stream(), stream_lock=threading.Lock())
        assert get_attached_codex_app_server_transport() is handle.transport
        handle.transport.send_request(
            {"id": "req-bootstrap-stream", "method": "item/tool/requestUserInput", "params": {}}
        )
        handle.close()
        assert get_attached_codex_app_server_transport() is original
        assert events == [
            ("write", '{"id": "req-bootstrap-stream", "method": "item/tool/requestUserInput", "params": {}}\n'),
            ("flush", ""),
        ]
    finally:
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_line_writer_returns_closeable_handle():
    original = BufferedCodexAppServerTransport()
    events: list[tuple[str, str]] = []

    attach_codex_app_server_transport(original)
    try:
        handle = bootstrap_codex_app_server_line_writer(lambda line: events.append(("line", line)))
        assert get_attached_codex_app_server_transport() is handle.transport
        handle.transport.send_request(
            {"id": "req-bootstrap-line", "method": "item/tool/requestUserInput", "params": {}}
        )
        handle.close()
        assert get_attached_codex_app_server_transport() is original
        assert events == [
            ("line", '{"id": "req-bootstrap-line", "method": "item/tool/requestUserInput", "params": {}}\n'),
        ]
    finally:
        detach_codex_app_server_transport()


def test_attached_codex_app_server_fd_context_writes_and_restores_previous():
    original = BufferedCodexAppServerTransport()
    fd, path = tempfile.mkstemp()
    os.close(fd)
    write_fd = os.open(path, os.O_WRONLY)

    attach_codex_app_server_transport(original)
    try:
        with attached_codex_app_server_fd(write_fd, stream_lock=threading.Lock()) as transport:
            assert get_attached_codex_app_server_transport() is transport
            transport.send_request(
                {"id": "req-fd", "method": "item/tool/requestUserInput", "params": {}}
            )
        assert get_attached_codex_app_server_transport() is original
        with open(path, encoding="utf-8") as handle:
            assert handle.read() == '{"id": "req-fd", "method": "item/tool/requestUserInput", "params": {}}\n'
    finally:
        os.close(write_fd)
        os.unlink(path)
        detach_codex_app_server_transport()


def test_attached_codex_app_server_path_context_writes_and_restores_previous():
    original = BufferedCodexAppServerTransport()
    fd, path = tempfile.mkstemp()
    os.close(fd)

    attach_codex_app_server_transport(original)
    try:
        with attached_codex_app_server_path(path, stream_lock=threading.Lock()) as transport:
            assert get_attached_codex_app_server_transport() is transport
            transport.send_request(
                {"id": "req-path", "method": "item/tool/requestUserInput", "params": {}}
            )
        assert get_attached_codex_app_server_transport() is original
        with open(path, encoding="utf-8") as handle:
            assert handle.read() == '{"id": "req-path", "method": "item/tool/requestUserInput", "params": {}}\n'
    finally:
        os.unlink(path)
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_fd_returns_closeable_handle():
    original = BufferedCodexAppServerTransport()
    fd, path = tempfile.mkstemp()
    os.close(fd)
    write_fd = os.open(path, os.O_WRONLY)

    attach_codex_app_server_transport(original)
    try:
        handle = bootstrap_codex_app_server_fd(write_fd, stream_lock=threading.Lock())
        assert get_attached_codex_app_server_transport() is handle.transport
        handle.transport.send_request(
            {"id": "req-bootstrap-fd", "method": "item/tool/requestUserInput", "params": {}}
        )
        handle.close()
        assert get_attached_codex_app_server_transport() is original
        with open(path, encoding="utf-8") as handle_read:
            assert handle_read.read() == '{"id": "req-bootstrap-fd", "method": "item/tool/requestUserInput", "params": {}}\n'
    finally:
        os.close(write_fd)
        os.unlink(path)
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_path_returns_closeable_handle():
    original = BufferedCodexAppServerTransport()
    fd, path = tempfile.mkstemp()
    os.close(fd)

    attach_codex_app_server_transport(original)
    try:
        handle = bootstrap_codex_app_server_path(path, stream_lock=threading.Lock())
        assert get_attached_codex_app_server_transport() is handle.transport
        handle.transport.send_request(
            {"id": "req-bootstrap-path", "method": "item/tool/requestUserInput", "params": {}}
        )
        handle.close()
        assert get_attached_codex_app_server_transport() is original
        with open(path, encoding="utf-8") as handle_read:
            assert handle_read.read() == '{"id": "req-bootstrap-path", "method": "item/tool/requestUserInput", "params": {}}\n'
    finally:
        os.unlink(path)
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_from_env_prefers_fd():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    write_fd = os.open(path, os.O_WRONLY)
    try:
        handle = bootstrap_codex_app_server_from_env(
            env={
                ENV_CODEX_APP_SERVER_WRITER_FD: str(write_fd),
                ENV_CODEX_APP_SERVER_WRITER_PATH: "/tmp/should-not-win",
                ENV_CODEX_APP_SERVER_WRITER_ENCODING: "utf-8",
            },
            stream_lock=threading.Lock(),
        )
        assert handle is not None
        handle.transport.send_request(
            {"id": "req-env-fd", "method": "item/tool/requestUserInput", "params": {}}
        )
        handle.close()
        with open(path, encoding="utf-8") as handle_read:
            assert handle_read.read() == '{"id": "req-env-fd", "method": "item/tool/requestUserInput", "params": {}}\n'
    finally:
        os.close(write_fd)
        os.unlink(path)
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_from_env_uses_path_and_logs():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    logs: list[str] = []
    try:
        handle = bootstrap_codex_app_server_from_env(
            env={ENV_CODEX_APP_SERVER_WRITER_PATH: path},
            stream_lock=threading.Lock(),
            log_fn=logs.append,
        )
        assert handle is not None
        handle.transport.send_request(
            {"id": "req-env-path", "method": "item/tool/requestUserInput", "params": {}}
        )
        handle.close()
        with open(path, encoding="utf-8") as handle_read:
            assert handle_read.read() == '{"id": "req-env-path", "method": "item/tool/requestUserInput", "params": {}}\n'
        assert any("attached writer path" in line for line in logs)
    finally:
        os.unlink(path)
        detach_codex_app_server_transport()


def test_bootstrap_codex_app_server_from_env_invalid_fd_logs_and_returns_none():
    logs: list[str] = []
    handle = bootstrap_codex_app_server_from_env(
        env={ENV_CODEX_APP_SERVER_WRITER_FD: "not-an-int"},
        log_fn=logs.append,
    )
    assert handle is None
    assert any("invalid writer fd" in line for line in logs)
