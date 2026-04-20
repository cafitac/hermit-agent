from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException
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
async def test_create_task_endpoint_preserves_explicit_startup_values():
    from hermit_agent.gateway._singletons import sse_manager
    from hermit_agent.gateway.routes.tasks import TaskRequest, create_task_endpoint
    from hermit_agent.gateway.task_store import delete_task, get_task

    background = BackgroundTasks()
    result = await create_task_endpoint(
        req=TaskRequest(
            task="do work",
            cwd="/tmp/project",
            model="glm-5.1",
            max_turns=9,
            parent_session_id="parent-123",
        ),
        background=background,
        auth=SimpleNamespace(user="tester"),
    )
    task_id = result["task_id"]
    state = get_task(task_id)

    try:
        assert result == {"task_id": task_id, "status": "running"}
        assert state is not None
        assert state.parent_session_id == "parent-123"
        assert len(background.tasks) == 1
        scheduled = background.tasks[0]
        assert scheduled.kwargs["task_id"] == task_id
        assert scheduled.kwargs["task"] == "do work"
        assert scheduled.kwargs["cwd"] == "/tmp/project"
        assert scheduled.kwargs["user"] == "tester"
        assert scheduled.kwargs["model"] == "glm-5.1"
        assert scheduled.kwargs["max_turns"] == 9
        assert scheduled.kwargs["state"] is state
        assert task_id in sse_manager._queues
    finally:
        delete_task(task_id)
        sse_manager._queues.pop(task_id, None)


@pytest.mark.anyio
async def test_create_task_endpoint_returns_server_busy_error_when_no_worker_slot(monkeypatch):
    from hermit_agent.gateway.routes import tasks as tasks_mod
    from hermit_agent.gateway.routes.tasks import TaskRequest, create_task_endpoint

    monkeypatch.setattr(tasks_mod, "acquire_worker_slot", lambda: False)

    with pytest.raises(HTTPException) as exc:
        await create_task_endpoint(
            req=TaskRequest(task="do work", cwd="", model="", max_turns=2),
            background=BackgroundTasks(),
            auth=SimpleNamespace(user="tester"),
        )

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "server_busy"


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


@pytest.mark.anyio
async def test_missing_task_routes_raise_not_found():
    from hermit_agent.gateway.routes.tasks import (
        cancel_task,
        get_task_status,
        reply_task,
        stream_task,
        ReplyRequest,
    )

    auth = SimpleNamespace(user="tester")

    for call in (
        lambda: get_task_status(task_id="missing-task", auth=auth),
        lambda: stream_task(task_id="missing-task", auth=auth),
        lambda: reply_task(task_id="missing-task", req=ReplyRequest(message="yes"), auth=auth),
        lambda: cancel_task(task_id="missing-task", auth=auth),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "task_not_found"


@pytest.mark.anyio
async def test_reply_route_rejects_non_waiting_task():
    from hermit_agent.gateway.routes.tasks import ReplyRequest, reply_task
    from hermit_agent.gateway.task_runtime import create_registered_task_state
    from hermit_agent.gateway.task_store import delete_task

    auth = SimpleNamespace(user="tester")
    task_id, state = create_registered_task_state()
    state.status = "running"

    try:
        with pytest.raises(HTTPException) as exc:
            await reply_task(task_id=task_id, req=ReplyRequest(message="yes"), auth=auth)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "task_already_done"
        assert "waiting state" in exc.value.detail["message"]
    finally:
        delete_task(task_id)
