from __future__ import annotations

from .task_actions import cancel_task_state, enqueue_reply
from .task_runtime import TaskLaunch, prepare_task_launch
from .task_store import GatewayTaskState, get_task
from .task_views import add_waiting_prompt_fields


class GatewayTaskAPI:
    """Thin façade over gateway task runtime/state helpers."""

    def prepare_launch(
        self,
        *,
        task: str,
        cwd: str | None,
        model: str | None,
        max_turns: int,
        user: str,
        parent_session_id: str | None = None,
        strategy: str = "",
    ) -> TaskLaunch:
        return prepare_task_launch(
            task=task,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            user=user,
            parent_session_id=parent_session_id,
            strategy=strategy,
        )

    def get_state(self, task_id: str) -> GatewayTaskState | None:
        return get_task(task_id)

    def reply(self, state: GatewayTaskState, message: str) -> dict[str, str]:
        enqueue_reply(state, message)
        return {"status": "ok", "task_id": state.task_id}

    def cancel(self, state: GatewayTaskState) -> dict[str, str]:
        cancel_task_state(state)
        return {"status": "cancelled", "task_id": state.task_id}

    def status_payload(self, state: GatewayTaskState, *, include_kind: bool) -> dict[str, object]:
        result: dict[str, object] = {
            "task_id": state.task_id,
            "status": state.status,
            "token_totals": state.token_totals,
        }
        if state.orchestration:
            result["orchestration"] = dict(state.orchestration)
        if state.status in ("done", "error", "needs_review"):
            result["result"] = state.result
        return add_waiting_prompt_fields(result, state, include_kind=include_kind)
