from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks


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
