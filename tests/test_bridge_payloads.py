from __future__ import annotations

from hermit_agent.bridge_payloads import (
    build_interactive_message_request,
    build_interactive_session_request,
    build_ready_payload,
)


def test_build_ready_payload_matches_bridge_contract():
    payload = build_ready_payload(
        model="gpt-5.4",
        cwd="/tmp/project",
        version="1.2.3",
        commands={"/help": "Get help"},
    )

    assert payload == {
        "type": "ready",
        "model": "gpt-5.4",
        "session_id": "gateway",
        "cwd": "/tmp/project",
        "permission": "accept_edits",
        "version": "1.2.3",
        "commands": {"/help": "Get help"},
    }

def test_build_interactive_session_request_matches_private_bridge_shape():
    payload = build_interactive_session_request(
        cwd="/tmp/project",
        model="__auto__",
        parent_session_id="session-1",
        session_id="interactive-1",
    )

    assert payload == {
        "cwd": "/tmp/project",
        "model": "__auto__",
        "parent_session_id": "session-1",
        "session_id": "interactive-1",
    }


def test_build_interactive_message_request_matches_private_turn_shape():
    assert build_interactive_message_request(message="hello") == {"message": "hello"}
