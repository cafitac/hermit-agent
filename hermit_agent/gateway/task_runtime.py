from __future__ import annotations

import uuid

from ._singletons import sse_manager
from .task_store import GatewayTaskState, create_task


def create_registered_task_state(task_id: str | None = None) -> tuple[str, GatewayTaskState]:
    resolved_task_id = task_id or str(uuid.uuid4())
    state = create_task(resolved_task_id)
    sse_manager.register(resolved_task_id)
    return resolved_task_id, state
