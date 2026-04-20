from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import StreamingResponse


def test_help_slash_command_lists_available_commands():
    from hermit_agent.gateway.routes import tasks as tasks_mod

    result = tasks_mod._handle_slash_command("/help")

    assert result is not None
    assert result.startswith("Available commands:")
    assert "/help" in result


def test_status_and_resume_slash_commands_return_gateway_messages():
    from hermit_agent.gateway.routes import tasks as tasks_mod

    assert tasks_mod._handle_slash_command("/status") == "Gateway mode — /status is not yet supported."
    assert tasks_mod._handle_slash_command("/resume") == "Gateway mode does not support /resume."


@pytest.mark.anyio
async def test_create_task_endpoint_short_circuits_gateway_slash_commands():
    from hermit_agent.gateway.routes.tasks import TaskRequest, create_task_endpoint

    result = await create_task_endpoint(
        req=TaskRequest(task="/status", cwd="", model="", max_turns=1),
        background=BackgroundTasks(),
        auth=SimpleNamespace(user="tester"),
    )

    assert result == {
        "task_id": "instant",
        "status": "done",
        "result": "Gateway mode — /status is not yet supported.",
    }


@pytest.mark.anyio
async def test_create_task_endpoint_schedules_background_work_for_normal_tasks():
    from hermit_agent.gateway._singletons import sse_manager
    from hermit_agent.gateway.routes.tasks import TaskRequest, create_task_endpoint
    from hermit_agent.gateway.task_store import delete_task, get_task

    background = BackgroundTasks()
    result = await create_task_endpoint(
        req=TaskRequest(task="do work", cwd="", model="", max_turns=2),
        background=background,
        auth=SimpleNamespace(user="tester"),
    )
    task_id = result["task_id"]

    try:
        assert result == {"task_id": task_id, "status": "running"}
        assert len(background.tasks) == 1
        assert get_task(task_id) is not None
        assert task_id in sse_manager._queues
    finally:
        delete_task(task_id)
        sse_manager._queues.pop(task_id, None)


@pytest.mark.anyio
async def test_reply_status_and_cancel_routes_use_real_task_state():
    from hermit_agent.gateway.routes.tasks import (
        ReplyRequest,
        cancel_task,
        get_task_status,
        reply_task,
    )
    from hermit_agent.gateway.task_runtime import create_registered_task_state
    from hermit_agent.gateway.task_store import delete_task

    auth = SimpleNamespace(user="tester")
    task_id, state = create_registered_task_state()
    state.status = "waiting"
    state.waiting_kind = "permission_ask"
    state.question_queue.put({"question": "Allow?", "options": ["Yes", "No"]})

    try:
        status = await get_task_status(task_id=task_id, auth=auth)
        replied = await reply_task(task_id=task_id, req=ReplyRequest(message="yes"), auth=auth)
        cancelled = await cancel_task(task_id=task_id, auth=auth)

        assert status == {
            "task_id": task_id,
            "status": "waiting",
            "result": None,
            "token_totals": {"prompt_tokens": 0, "completion_tokens": 0},
            "question": "Allow?",
            "options": ["Yes", "No"],
            "kind": "permission_ask",
        }
        assert replied == {"status": "ok", "task_id": task_id}
        assert state.reply_queue.get_nowait() == "yes"
        assert cancelled == {"status": "cancelled", "task_id": task_id}
        assert state.cancel_event.is_set() is True
        assert state.reply_queue.get_nowait() == "__CANCELLED__"
    finally:
        delete_task(task_id)


@pytest.mark.anyio
async def test_stream_task_returns_sse_response_for_registered_task():
    from hermit_agent.gateway.routes.tasks import stream_task
    from hermit_agent.gateway.task_runtime import create_registered_task_state
    from hermit_agent.gateway.task_store import delete_task

    auth = SimpleNamespace(user="tester")
    task_id, _state = create_registered_task_state()

    try:
        response = await stream_task(task_id=task_id, auth=auth)
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
        assert response.headers["x-task-id"] == task_id
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
    finally:
        delete_task(task_id)
