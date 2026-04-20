from __future__ import annotations

from .task_store import GatewayTaskState


def is_waiting_for_reply(state: GatewayTaskState) -> bool:
    return state.status == "waiting"


def enqueue_reply(state: GatewayTaskState, message: str) -> None:
    state.reply_queue.put(message)


def cancel_task_state(state: GatewayTaskState) -> None:
    state.cancel_event.set()
    if is_waiting_for_reply(state):
        state.reply_queue.put("__CANCELLED__")
