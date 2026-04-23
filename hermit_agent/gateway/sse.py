from __future__ import annotations
import asyncio
import logging
from typing import AsyncGenerator, Literal
from pydantic import BaseModel

logger = logging.getLogger("hermit_agent.gateway.sse")


class SSEEvent(BaseModel):
    type: Literal[
        # Existing types (semantics unchanged)
        "progress", "tool_result", "waiting", "reply_ack", "done", "error", "cancelled",
        # New types (bridge TUI only)
        "streaming",      # token-level streaming → token field
        "stream_end",     # streaming end
        "tool_use",       # tool execution start → tool_name, detail fields
        "status",         # status info → turns, ctx_pct, tokens, model, etc.
        "permission_ask", # permission request (distinct from waiting) → tool_name, question fields
        "text",           # final text response → reuses message field
        "model_changed",  # model change → old_model, new_model fields
    ]
    step: str = ""
    message: str = ""
    question: str = ""
    options: list[str] = []
    result: str = ""
    # New fields (bridge TUI only)
    token: str = ""
    tool_name: str = ""
    method: str = ""
    detail: str = ""
    content: str = ""
    is_error: bool = False
    turns: int = 0
    ctx_pct: int = 0
    tokens: int = 0
    model: str = ""
    session_id: str = ""
    old_model: str = ""
    new_model: str = ""
    permission: str = ""
    version: str = ""
    auto_agents: int = 0
    modified_files: int = 0


class SSEManager:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register(self, task_id: str, max_queue: int = 200) -> None:
        """Pre-register before calling SSE stream(). Must be called before starting the background task."""
        if task_id not in self._queues:
            self._queues[task_id] = asyncio.Queue(maxsize=max_queue)

    def publish_threadsafe(self, task_id: str, event: SSEEvent) -> None:
        """Can be called from the executor thread."""
        if not self._loop or task_id not in self._queues:
            return
        q = self._queues[task_id]
        try:
            self._loop.call_soon_threadsafe(q.put_nowait, event)
        except asyncio.QueueFull:
            try:
                self._loop.call_soon_threadsafe(q.get_nowait)
                self._loop.call_soon_threadsafe(q.put_nowait, event)
                logger.warning("SSE queue full for %s, dropped oldest", task_id)
            except Exception:
                pass

    async def stream(self, task_id: str) -> AsyncGenerator[str, None]:
        """SSE event stream. 30s keepalive."""
        q = self._queues.get(task_id)
        if q is None:
            q = asyncio.Queue(maxsize=200)
            self._queues[task_id] = q
        keepalive_interval = 30.0
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=keepalive_interval)
                    yield f"data: {event.model_dump_json()}\n\n"
                    if event.type in ("done", "error", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            self._queues.pop(task_id, None)
