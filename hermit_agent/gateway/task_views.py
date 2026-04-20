from __future__ import annotations

from .task_store import GatewayTaskState


def peek_waiting_prompt(state: GatewayTaskState) -> dict[str, object]:
    try:
        q_item = state.question_queue.get_nowait()
    except Exception:
        return {}

    try:
        return {
            "question": q_item.get("question", ""),
            "options": q_item.get("options", []),
        }
    finally:
        state.question_queue.put_nowait(q_item)


def add_waiting_prompt_fields(
    result: dict[str, object],
    state: GatewayTaskState,
    *,
    include_kind: bool,
) -> dict[str, object]:
    if state.status != "waiting":
        return result

    result.update(peek_waiting_prompt(state))
    if include_kind:
        result["kind"] = state.waiting_kind or "waiting"
    return result
