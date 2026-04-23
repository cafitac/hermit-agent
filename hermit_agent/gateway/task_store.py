from __future__ import annotations
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class TaskStateProtocol(Protocol):
    task_id: str
    cancel_event: threading.Event
    question_queue: queue.Queue
    reply_queue: queue.Queue
    result_queue: queue.Queue


@dataclass
class GatewayTaskState:
    task_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    question_queue: queue.Queue = field(default_factory=queue.Queue)
    reply_queue: queue.Queue = field(default_factory=queue.Queue)
    result_queue: queue.Queue = field(default_factory=queue.Queue)
    status: str = "running"       # running | waiting | done | error | cancelled
    waiting_kind: str | None = None
    waiting_prompt: dict[str, object] | None = None
    result: str | None = None
    token_totals: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    parent_session_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    TTL_SECONDS: int = 3600

    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.TTL_SECONDS

    def is_waiting_for_reply(self) -> bool:
        return self.status == "waiting"

    def enqueue_reply(self, message: str) -> None:
        self.reply_queue.put(message)

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.is_waiting_for_reply():
            self.reply_queue.put("__CANCELLED__")

    def peek_waiting_prompt(self) -> dict[str, object]:
        if self.waiting_prompt is not None:
            prompt = dict(self.waiting_prompt)
            prompt.setdefault("method", "")
            return prompt
        try:
            q_item = self.question_queue.get_nowait()
        except Exception:
            return {}

        try:
            return {
                "question": q_item.get("question", ""),
                "options": q_item.get("options", []),
                "tool_name": q_item.get("tool_name", ""),
                "method": q_item.get("method", ""),
            }
        finally:
            self.question_queue.put_nowait(q_item)

    def add_waiting_prompt_fields(self, result: dict[str, object], *, include_kind: bool) -> dict[str, object]:
        if not self.is_waiting_for_reply():
            return result

        result.update(self.peek_waiting_prompt())
        if include_kind:
            result["kind"] = self.waiting_kind or "waiting"
        return result


_tasks: dict[str, GatewayTaskState] = {}
_tasks_lock = threading.Lock()

_workers_sem: threading.Semaphore | None = None
_MAX_WORKERS_COUNT: int = 20


def init_semaphore(max_workers: int) -> None:
    global _workers_sem, _MAX_WORKERS_COUNT
    _workers_sem = threading.Semaphore(max_workers)
    _MAX_WORKERS_COUNT = max_workers


def acquire_worker_slot() -> bool:
    """For 503 responses. Returns False if no slot available."""
    return _workers_sem.acquire(blocking=False) if _workers_sem else True


def release_worker_slot() -> None:
    """Must be called in finally on task completion — omission causes permanent 503."""
    if _workers_sem:
        _workers_sem.release()


def active_worker_count() -> int:
    if _workers_sem is None:
        return 0
    return _MAX_WORKERS_COUNT - _workers_sem._value  # type: ignore[attr-defined]


def create_task(task_id: str) -> GatewayTaskState:
    state = GatewayTaskState(task_id=task_id)
    with _tasks_lock:
        _tasks[task_id] = state
    return state


def get_task(task_id: str) -> GatewayTaskState | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def delete_task(task_id: str) -> None:
    with _tasks_lock:
        _tasks.pop(task_id, None)


def expire_tasks(sse_manager=None) -> None:
    """Clean up TTL-expired tasks."""
    with _tasks_lock:
        expired = [tid for tid, s in _tasks.items() if s.is_expired()]
        for tid in expired:
            if sse_manager is not None:
                from .sse import SSEEvent
                sse_manager.publish_threadsafe(tid, SSEEvent(
                    type="cancelled", message="task expired (TTL)"
                ))
            del _tasks[tid]
