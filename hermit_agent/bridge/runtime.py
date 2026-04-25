from __future__ import annotations

import queue
import threading


class BridgeRuntime:
    """Small state holder for bridge.py gateway-mode runtime."""

    def __init__(self, msg_queue: queue.Queue):
        self.msg_queue = msg_queue
        self.current_interactive_session_id: str | None = None
        self.interactive_waiting: bool = False
        self.sse_shutdown = threading.Event()

    def reset_sse_shutdown(self) -> threading.Event:
        self.sse_shutdown = threading.Event()
        return self.sse_shutdown

    def clear_interactive_waiting(self) -> None:
        self.interactive_waiting = False

    def mark_interactive_waiting(self) -> None:
        self.interactive_waiting = True
