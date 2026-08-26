from __future__ import annotations

import uuid
from dataclasses import dataclass

from ._singletons import sse_manager
from .task_models import normalize_requested_model, normalize_task_cwd
from .task_store import GatewayTaskState, create_task


@dataclass(frozen=True)
class TaskLaunch:
    task_id: str
    state: GatewayTaskState
    cwd: str
    model: str
    max_turns: int
    task: str
    user: str
    strategy: str


def create_registered_task_state(task_id: str | None = None) -> tuple[str, GatewayTaskState]:
    resolved_task_id = task_id or str(uuid.uuid4())
    state = create_task(resolved_task_id)
    sse_manager.register(resolved_task_id)
    return resolved_task_id, state


def prepare_task_launch(
    *,
    task: str,
    cwd: str | None,
    model: str | None,
    max_turns: int,
    user: str,
    strategy: str = "",
    parent_session_id: str | None = None,
) -> TaskLaunch:
    task_id, state = create_registered_task_state()
    state.parent_session_id = parent_session_id
    return TaskLaunch(
        task_id=task_id,
        state=state,
        cwd=normalize_task_cwd(cwd),
        model=normalize_requested_model(model),
        max_turns=max_turns,
        task=task,
        user=user,
        strategy=strategy,
    )
