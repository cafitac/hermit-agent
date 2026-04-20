from __future__ import annotations

import asyncio

import pytest


class _DummyMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.mark.anyio
async def test_run_task_leaves_slash_preprocessing_to_task_runner(monkeypatch):
    import os

    import hermit_agent.gateway.mcp_tools as mcp_tools_mod
    import hermit_agent.gateway.task_runner as task_runner_mod
    from hermit_agent.gateway._singletons import sse_manager
    from hermit_agent.gateway.task_store import delete_task, get_task

    dummy = _DummyMCP()
    captured: dict[str, object] = {}

    async def fake_run_task_async(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(task_runner_mod, "run_task_async", fake_run_task_async)

    mcp_tools_mod.register_mcp_tools(dummy)
    run_task = dummy.tools["run_task"]

    result = await run_task(task="/plan\nbody", cwd="", model="", max_turns=7)
    await asyncio.sleep(0)
    task_id = result["task_id"]
    state = get_task(task_id)

    try:
        assert result == {"status": "running", "task_id": task_id}
        assert task_id in sse_manager._queues
        assert state is not None
        assert captured["task_id"] == task_id
        assert captured["state"] is state
        assert captured["task"] == "/plan\nbody"
        assert captured["cwd"] == os.getcwd()
        assert captured["model"] == "__auto__"
        assert captured["max_turns"] == 7
    finally:
        delete_task(task_id)
        sse_manager._queues.pop(task_id, None)


@pytest.mark.anyio
async def test_check_reply_and_cancel_task_use_real_state():
    import hermit_agent.gateway.mcp_tools as mcp_tools_mod
    from hermit_agent.gateway.task_store import create_task, delete_task

    dummy = _DummyMCP()
    mcp_tools_mod.register_mcp_tools(dummy)
    check_task = dummy.tools["check_task"]
    reply_task = dummy.tools["reply_task"]
    cancel_task = dummy.tools["cancel_task"]

    state = create_task("task-check")
    state.status = "waiting"
    state.waiting_kind = "permission_ask"
    state.question_queue.put({"question": "Allow?", "options": ["Yes", "No"]})

    try:
        checked = await check_task("task-check")
        replied = await reply_task("task-check", "yes")
        cancelled = await cancel_task("task-check")

        assert checked == {
            "task_id": "task-check",
            "status": "waiting",
            "token_totals": {"prompt_tokens": 0, "completion_tokens": 0},
            "question": "Allow?",
            "options": ["Yes", "No"],
        }
        assert replied == {"status": "ok", "task_id": "task-check"}
        assert state.reply_queue.get_nowait() == "yes"
        assert cancelled == {"status": "cancelled", "task_id": "task-check"}
        assert state.cancel_event.is_set() is True
        assert state.reply_queue.get_nowait() == "__CANCELLED__"
    finally:
        delete_task("task-check")


def test_create_registered_task_state_registers_real_task_and_sse_queue():
    from hermit_agent.gateway._singletons import sse_manager
    from hermit_agent.gateway.task_runtime import create_registered_task_state
    from hermit_agent.gateway.task_store import delete_task, get_task

    task_id, state = create_registered_task_state()

    try:
        assert get_task(task_id) is state
        assert task_id in sse_manager._queues
    finally:
        delete_task(task_id)
        sse_manager._queues.pop(task_id, None)
