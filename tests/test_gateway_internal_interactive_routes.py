from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse


@pytest.mark.anyio
async def test_create_internal_interactive_session_returns_private_session(monkeypatch):
    from hermit_agent.gateway.routes import interactive_sessions as mod

    runtime = SimpleNamespace(session_id="interactive-1", status="active")
    monkeypatch.setattr(mod, "_create_interactive_runtime_for_request", lambda req: runtime)

    result = await mod.create_interactive_session_endpoint(
        req=mod.InteractiveSessionRequest(cwd="/tmp", model="__auto__"),
        auth=SimpleNamespace(user="tester"),
    )

    assert result == {"session_id": "interactive-1", "status": "active", "mode": "interactive"}


@pytest.mark.anyio
async def test_send_internal_interactive_message_and_stream(monkeypatch):
    from hermit_agent.gateway.routes import interactive_sessions as mod

    runtime = SimpleNamespace(session_id="interactive-1")
    monkeypatch.setattr(mod, "get_interactive_session", lambda session_id: runtime)
    monkeypatch.setattr(mod, "submit_interactive_turn", lambda runtime, message: "running")

    result = await mod.send_interactive_message(
        session_id="interactive-1",
        req=mod.InteractiveMessageRequest(message="hello"),
        auth=SimpleNamespace(user="tester"),
    )
    response = await mod.stream_interactive_session(
        session_id="interactive-1",
        auth=SimpleNamespace(user="tester"),
    )

    assert result == {"session_id": "interactive-1", "status": "running"}
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert response.headers["x-session-id"] == "interactive-1"


@pytest.mark.anyio
async def test_get_internal_interactive_status_includes_waiting_snapshot(monkeypatch):
    from hermit_agent.gateway.routes import interactive_sessions as mod
    from hermit_agent.interactive_prompts import create_interactive_prompt

    runtime = SimpleNamespace(
        session_id="interactive-1",
        status="waiting",
        parent_session_id="parent-1",
        waiting_prompt=create_interactive_prompt(
            task_id="interactive-1",
            question="Which environment?",
            options=["staging", "prod"],
            prompt_kind="waiting",
            tool_name="ask",
        ),
    )
    monkeypatch.setattr(mod, "get_interactive_session", lambda session_id: runtime)

    result = await mod.get_interactive_session_status(
        session_id="interactive-1",
        auth=SimpleNamespace(user="tester"),
    )

    assert result == {
        "session_id": "interactive-1",
        "status": "waiting",
        "parent_session_id": "parent-1",
        "waiting_kind": "waiting",
        "waiting_prompt": {
            "question": "Which environment?",
            "options": ["staging", "prod"],
            "tool_name": "ask",
        },
    }


@pytest.mark.anyio
async def test_internal_interactive_reply_and_cancel_routes(monkeypatch):
    from hermit_agent.gateway.routes import interactive_sessions as mod

    runtime = SimpleNamespace(session_id="interactive-1")
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "get_interactive_session", lambda session_id: runtime)
    monkeypatch.setattr(mod, "reply_to_interactive_session", lambda runtime, message: seen.append(("reply", message)))
    monkeypatch.setattr(mod, "cancel_interactive_session", lambda runtime: seen.append(("cancel", runtime.session_id)))

    reply_result = await mod.reply_interactive_session(
        session_id="interactive-1",
        req=mod.InteractiveMessageRequest(message="staging"),
        auth=SimpleNamespace(user="tester"),
    )
    cancel_result = await mod.delete_interactive_session_endpoint(
        session_id="interactive-1",
        auth=SimpleNamespace(user="tester"),
    )

    assert reply_result == {"status": "ok", "session_id": "interactive-1"}
    assert cancel_result == {"status": "cancelled", "session_id": "interactive-1"}
    assert seen == [("reply", "staging"), ("cancel", "interactive-1")]


@pytest.mark.anyio
async def test_internal_interactive_routes_raise_not_found(monkeypatch):
    from hermit_agent.gateway.routes import interactive_sessions as mod

    monkeypatch.setattr(mod, "get_interactive_session", lambda session_id: None)

    for call in (
        lambda: mod.send_interactive_message(
            session_id="missing",
            req=mod.InteractiveMessageRequest(message="hello"),
            auth=SimpleNamespace(user="tester"),
        ),
        lambda: mod.stream_interactive_session(
            session_id="missing",
            auth=SimpleNamespace(user="tester"),
        ),
        lambda: mod.reply_interactive_session(
            session_id="missing",
            req=mod.InteractiveMessageRequest(message="yes"),
            auth=SimpleNamespace(user="tester"),
        ),
        lambda: mod.delete_interactive_session_endpoint(
            session_id="missing",
            auth=SimpleNamespace(user="tester"),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 404
