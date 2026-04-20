from __future__ import annotations

import asyncio
import json
import threading
import time


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
    import hermit_agent.mcp_server as m

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
