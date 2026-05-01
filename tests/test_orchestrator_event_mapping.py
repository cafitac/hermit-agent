from __future__ import annotations

from hermit_agent.channels_core.event_adapters import ChannelAction
from hermit_agent.orchestrators import (
    TaskEvent,
    TaskEventKind,
    channel_action_to_task_event,
    sse_event_to_task_event,
    task_status_payload_to_task_event,
)


def test_sse_running_and_progress_events_map_to_neutral_task_events_without_mutation():
    running_payload = {"type": "reply_ack", "extra": {"nested": True}}
    progress_payload = {"type": "progress", "message": 123, "step": "lint"}

    running = sse_event_to_task_event("task-1", running_payload)
    progress = sse_event_to_task_event("task-1", progress_payload)

    assert running == TaskEvent(
        task_id="task-1",
        kind=TaskEventKind.RUNNING,
        payload={"type": "reply_ack", "extra": {"nested": True}},
    )
    assert progress == TaskEvent(
        task_id="task-1",
        kind=TaskEventKind.PROGRESS,
        message="123",
        payload={"type": "progress", "message": 123, "step": "lint"},
    )
    assert running_payload == {"type": "reply_ack", "extra": {"nested": True}}


def test_sse_waiting_event_preserves_prompt_metadata():
    event = {
        "type": "permission_ask",
        "question": "Run tests?",
        "options": ["Yes", "No"],
        "tool_name": "bash",
        "method": "item/commandExecution/requestApproval",
        "request_id": "req-1",
    }

    mapped = sse_event_to_task_event("task-2", event)

    assert mapped == TaskEvent(
        task_id="task-2",
        kind=TaskEventKind.WAITING,
        message="Run tests?",
        payload={
            "type": "permission_ask",
            "question": "Run tests?",
            "options": ("Yes", "No"),
            "tool_name": "bash",
            "method": "item/commandExecution/requestApproval",
            "request_id": "req-1",
            "prompt_kind": "permission_ask",
        },
    )


def test_sse_done_error_cancelled_and_unknown_events_are_defensive():
    assert sse_event_to_task_event("task-3", {"type": "done", "result": "complete", "tokens": 7}) == TaskEvent(
        task_id="task-3",
        kind=TaskEventKind.DONE,
        message="complete",
        payload={"type": "done", "result": "complete", "tokens": 7},
    )
    assert sse_event_to_task_event("task-3", {"type": "error", "message": "boom"}) == TaskEvent(
        task_id="task-3",
        kind=TaskEventKind.ERROR,
        message="boom",
        payload={"type": "error", "message": "boom"},
    )
    assert sse_event_to_task_event("task-3", {"type": "cancelled"}) == TaskEvent(
        task_id="task-3",
        kind=TaskEventKind.CANCELLED,
        message="Task cancelled",
        payload={"type": "cancelled"},
    )
    assert sse_event_to_task_event("task-3", {"type": "streaming", "token": "partial"}) is None


def test_channel_action_mapping_covers_existing_action_surface():
    assert channel_action_to_task_event(
        "task-4",
        ChannelAction(
            kind="prompt",
            question="Need input",
            options=("A", "B"),
            prompt_kind="waiting",
            tool="ask",
            method="item/tool/requestUserInput",
        ),
    ) == TaskEvent(
        task_id="task-4",
        kind=TaskEventKind.WAITING,
        message="Need input",
        payload={
            "question": "Need input",
            "options": ("A", "B"),
            "prompt_kind": "waiting",
            "tool_name": "ask",
            "method": "item/tool/requestUserInput",
        },
    )
    assert channel_action_to_task_event("task-4", ChannelAction(kind="done", message="ok")) == TaskEvent(
        task_id="task-4",
        kind=TaskEventKind.DONE,
        message="ok",
        payload={"message": "ok"},
    )
    assert channel_action_to_task_event("task-4", ChannelAction(kind="error", message="boom")) == TaskEvent(
        task_id="task-4",
        kind=TaskEventKind.ERROR,
        message="boom",
        payload={"message": "boom"},
    )
    assert channel_action_to_task_event("task-4", ChannelAction(kind="running")) == TaskEvent(
        task_id="task-4",
        kind=TaskEventKind.RUNNING,
        payload={},
    )


def test_task_status_payload_mapping_matches_gateway_status_responses():
    waiting = task_status_payload_to_task_event(
        {
            "task_id": "task-5",
            "status": "waiting",
            "kind": "permission_ask",
            "question": "Approve?",
            "options": ["Yes", "No"],
            "tool_name": "bash",
        }
    )
    done = task_status_payload_to_task_event({"task_id": "task-5", "status": "done", "result": "finished"})

    assert waiting == TaskEvent(
        task_id="task-5",
        kind=TaskEventKind.WAITING,
        message="Approve?",
        payload={
            "task_id": "task-5",
            "status": "waiting",
            "kind": "permission_ask",
            "question": "Approve?",
            "options": ("Yes", "No"),
            "tool_name": "bash",
            "prompt_kind": "permission_ask",
        },
    )
    assert done == TaskEvent(
        task_id="task-5",
        kind=TaskEventKind.DONE,
        message="finished",
        payload={"task_id": "task-5", "status": "done", "result": "finished"},
    )
    assert task_status_payload_to_task_event({"status": "running"}) is None
