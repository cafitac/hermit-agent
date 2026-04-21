from __future__ import annotations

import queue
import threading


class BridgeRuntime:
    """Small state holder for bridge.py gateway-mode runtime."""

    def __init__(self, msg_queue: queue.Queue):
        self.msg_queue = msg_queue
        self.current_task_id: str | None = None
        self.sse_shutdown = threading.Event()

    def reset_sse_shutdown(self) -> threading.Event:
        self.sse_shutdown = threading.Event()
        return self.sse_shutdown

    def clear_current_task(self) -> None:
        self.current_task_id = None
