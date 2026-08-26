from __future__ import annotations


def register_mcp_tools(mcp) -> None:
    """Register 4 tools on the FastMCP instance."""

    from .task_actions import is_waiting_for_reply
    from .task_api import GatewayTaskAPI
    from .task_store import acquire_worker_slot
    from .task_runner import run_task_async
    import asyncio
    api = GatewayTaskAPI()

    @mcp.tool()
    async def run_task(
        task: str,
        cwd: str = "",
        model: str = "",
        max_turns: int = 200,
        strategy: str = "single",
    ) -> dict:
        """Run a task in the background and return the task_id."""
        from .errors import ErrorCode, mcp_error

        if not acquire_worker_slot():
            return mcp_error(ErrorCode.SERVER_BUSY)

        launch = api.prepare_launch(
            task=task,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            user="mcp",
            strategy=strategy,
        )

        asyncio.create_task(run_task_async(
            task_id=launch.task_id,
            task=launch.task,
            cwd=launch.cwd,
            user=launch.user,
            model=launch.model,
            max_turns=launch.max_turns,
            state=launch.state,
            strategy=launch.strategy,
        ))

        return {"status": "running", "task_id": launch.task_id}

    @mcp.tool()
    async def reply_task(task_id: str, message: str) -> dict:
        """Deliver a user reply to a task in waiting state."""
        from .errors import ErrorCode, mcp_error

        state = api.get_state(task_id)
        if not state:
            return mcp_error(ErrorCode.TASK_NOT_FOUND, f"task {task_id} not found")
        if not is_waiting_for_reply(state):
            return mcp_error(
                ErrorCode.TASK_ALREADY_DONE,
                f"task is not waiting (status={state.status})",
            )

        return api.reply(state, message)

    @mcp.tool()
    async def check_task(task_id: str) -> dict:
        """Query task status and result."""
        from .errors import ErrorCode, mcp_error

        state = api.get_state(task_id)
        if not state:
            return mcp_error(ErrorCode.TASK_NOT_FOUND, f"task {task_id} not found")
        return api.status_payload(state, include_kind=False)

    @mcp.tool()
    async def cancel_task(task_id: str) -> dict:
        """Cancel a running task."""
        from .errors import ErrorCode, mcp_error

        state = api.get_state(task_id)
        if not state:
            return mcp_error(ErrorCode.TASK_NOT_FOUND, f"task {task_id} not found")
        return api.cancel(state)
