from __future__ import annotations


from hermit_agent.channels_core.approvals import ApprovalDecision, parse_permission_reply
from hermit_agent.channels_core.event_adapters import (
    ChannelAction,
    bridge_messages_from_sse_event,
    channel_action_from_sse_event,
)


def test_parse_permission_reply_variants():
    assert parse_permission_reply("yolo") == ApprovalDecision(True, True)
    assert parse_permission_reply("Always allow (yolo)") == ApprovalDecision(True, True)
    assert parse_permission_reply("no") == ApprovalDecision(False, False)
    assert parse_permission_reply("Yes (once)") == ApprovalDecision(True, False)


def test_bridge_messages_from_waiting_event():
    msgs = bridge_messages_from_sse_event(
        {"type": "waiting", "question": "Need input", "options": ["A", "B"]},
        now=lambda: 123.0,
    )
    assert msgs == [{
        "type": "permission_ask",
        "tool": "ask",
        "summary": "Need input",
        "options": ["A", "B"],
    }]


def test_bridge_messages_from_tool_use_event():
    msgs = bridge_messages_from_sse_event(
        {"type": "tool_use", "tool_name": "bash", "detail": "ls -la"},
        now=lambda: 42.5,
    )
    assert msgs == [{
        "type": "tool_use",
        "name": "bash",
        "detail": "ls -la",
        "ts": 42.5,
    }]


def test_channel_action_from_sse_prompt_event():
    action = channel_action_from_sse_event(
        {"type": "permission_ask", "question": "[Permission request]", "options": ["Yes", "No"]}
    )
    assert action == ChannelAction(
        kind="prompt",
        question="[Permission request]",
        options=("Yes", "No"),
        prompt_kind="permission_ask",
        tool="bash",
    )


def test_channel_action_from_done_and_reply_ack_events():
    assert channel_action_from_sse_event({"type": "done", "result": "ok"}) == ChannelAction(
        kind="done",
        message="ok",
    )
    assert channel_action_from_sse_event({"type": "reply_ack"}) == ChannelAction(kind="running")
