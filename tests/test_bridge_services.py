from __future__ import annotations

from hermit_agent.bridge_services import (
    load_auto_recap_text,
    resolve_display_model,
    submit_bridge_task,
)


def test_resolve_display_model_uses_requested_model_when_explicit():
    result = resolve_display_model(
        requested_model="gpt-5.4",
        cwd="/tmp",
        load_settings=lambda cwd=None: {"model": "glm-5.1"},
        get_primary_model=lambda cfg, available_only=False: "glm-5.1",
    )
    assert result == "gpt-5.4"


def test_resolve_display_model_uses_primary_model_for_auto():
    result = resolve_display_model(
        requested_model="__auto__",
        cwd="/tmp",
        load_settings=lambda cwd=None: {"model": "glm-5.1"},
        get_primary_model=lambda cfg, available_only=False: "gpt-5.4" if available_only else "glm-5.1",
    )
    assert result == "gpt-5.4"


def test_load_auto_recap_text_filters_empty_marker():
    assert load_auto_recap_text(
        cwd="/tmp",
        should_auto_recap=lambda cwd: True,
        generate_recap=lambda cwd: "No recent session found.",
    ) is None
    assert load_auto_recap_text(
        cwd="/tmp",
        should_auto_recap=lambda cwd: True,
        generate_recap=lambda cwd: "Carry this forward",
    ) == "[Auto-recap of last session]\nCarry this forward"


def test_submit_bridge_task_delegates_to_client_with_built_payload():
    class _Client:
        def __init__(self):
            self.payload = None

        def create_task_payload(self, **kwargs):
            self.payload = kwargs
            return {"task_id": "task-1", "status": "running"}

    client = _Client()
    result = submit_bridge_task(
        client=client,
        task="do work",
        cwd="/tmp",
        model="__auto__",
        max_turns=3,
        parent_session_id="sess-1",
        build_gateway_task_request=lambda **kwargs: kwargs,
    )

    assert result == {"task_id": "task-1", "status": "running"}
    assert client.payload["task"] == "do work"
    assert client.payload["parent_session_id"] == "sess-1"
