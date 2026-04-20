from __future__ import annotations
import logging
import os
import uuid

logger = logging.getLogger("hermit_agent.gateway.mcp_tools")


def register_mcp_tools(mcp) -> None:
    """Register 4 tools on the FastMCP instance."""

    from .task_actions import cancel_task_state, enqueue_reply, is_waiting_for_reply
    from .task_store import acquire_worker_slot, create_task, get_task
    from .task_views import add_waiting_prompt_fields
    from ._singletons import sse_manager
    from .task_runner import run_task_async
    import asyncio

    @mcp.tool()
    async def run_task(
        task: str,
        cwd: str = "",
        model: str = "",
        max_turns: int = 200,
    ) -> dict:
        """Run a task in the background and return the task_id."""
        from .errors import ErrorCode, mcp_error

        if not acquire_worker_slot():
            return mcp_error(ErrorCode.SERVER_BUSY)

        task_id = str(uuid.uuid4())
        work_cwd = cwd or os.getcwd()
        use_model = model or "__auto__"

        state = create_task(task_id)
        sse_manager.register(task_id)

        if task.strip().startswith("/"):
            slash_line = task.strip().splitlines()[0]
            try:
                from ..loop import _preprocess_slash_command
                task = _preprocess_slash_command(task, slash_line, work_cwd)
            except Exception as e:
                logger.warning("slash command preprocessing failed: %s", e)

        asyncio.create_task(run_task_async(
            task_id=task_id,
            task=task,
            cwd=work_cwd,
            user="mcp",
            model=use_model,
            max_turns=max_turns,
            state=state,
        ))

        return {"status": "running", "task_id": task_id}

    @mcp.tool()
    async def reply_task(task_id: str, message: str) -> dict:
        """Deliver a user reply to a task in waiting state."""
        from .errors import ErrorCode, mcp_error

        state = get_task(task_id)
        if not state:
            return mcp_error(ErrorCode.TASK_NOT_FOUND, f"task {task_id} not found")
        if not is_waiting_for_reply(state):
            return mcp_error(
                ErrorCode.TASK_ALREADY_DONE,
                f"task is not waiting (status={state.status})",
            )

        enqueue_reply(state, message)
        return {"status": "ok", "task_id": task_id}

    @mcp.tool()
    async def check_task(task_id: str) -> dict:
        """Query task status and result."""
        from .errors import ErrorCode, mcp_error

        state = get_task(task_id)
        if not state:
            return mcp_error(ErrorCode.TASK_NOT_FOUND, f"task {task_id} not found")

        result = {
            "task_id": task_id,
            "status": state.status,
            "token_totals": state.token_totals,
        }
        if state.status in ("done", "error"):
            result["result"] = state.result
        return add_waiting_prompt_fields(result, state, include_kind=False)

    @mcp.tool()
    async def cancel_task(task_id: str) -> dict:
        """Cancel a running task."""
        from .errors import ErrorCode, mcp_error

        state = get_task(task_id)
        if not state:
            return mcp_error(ErrorCode.TASK_NOT_FOUND, f"task {task_id} not found")

        cancel_task_state(state)
        return {"status": "cancelled", "task_id": task_id}
