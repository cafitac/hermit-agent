from __future__ import annotations

from hermit_agent.gateway.task_actions import cancel_task_state, enqueue_reply, is_waiting_for_reply
from hermit_agent.gateway.task_views import add_waiting_prompt_fields, peek_waiting_prompt
from hermit_agent.gateway.task_store import GatewayTaskState


def test_peek_waiting_prompt_returns_question_and_preserves_queue():
    state = GatewayTaskState(task_id="t1")
    prompt = {"question": "Allow?", "options": ["Yes", "No"]}
    state.question_queue.put(prompt)

    assert state.peek_waiting_prompt() == {**prompt, "tool_name": "", "method": ""}
    result = peek_waiting_prompt(state)

    assert result == {**prompt, "tool_name": "", "method": ""}
    assert state.question_queue.qsize() == 1
    assert state.question_queue.get_nowait() == prompt


def test_waiting_status_payload_includes_kind_and_prompt():
    state = GatewayTaskState(task_id="t2")
    state.status = "waiting"
    state.waiting_kind = "permission_ask"
    state.token_totals = {"prompt_tokens": 1, "completion_tokens": 2}
    state.question_queue.put({"question": "[Permission request] bash", "options": ["Yes (once)", "No"]})

    result = {
        "task_id": state.task_id,
        "status": state.status,
        "result": state.result,
        "token_totals": state.token_totals,
    }
    assert state.add_waiting_prompt_fields(dict(result), include_kind=True)["kind"] == "permission_ask"
    result = add_waiting_prompt_fields(result, state, include_kind=True)

    assert result == {
        "task_id": "t2",
        "status": "waiting",
        "result": None,
        "token_totals": {"prompt_tokens": 1, "completion_tokens": 2},
        "question": "[Permission request] bash",
        "options": ["Yes (once)", "No"],
        "tool_name": "",
        "method": "",
        "kind": "permission_ask",
    }


def test_waiting_status_payload_can_skip_kind_for_mcp_shape():
    state = GatewayTaskState(task_id="t3")
    state.status = "waiting"
    state.waiting_kind = "waiting"
    state.token_totals = {"prompt_tokens": 3, "completion_tokens": 4}
    state.question_queue.put({"question": "Continue?", "options": ["Yes", "No"], "tool_name": "ask"})

    result = {
        "task_id": state.task_id,
        "status": state.status,
        "token_totals": state.token_totals,
    }
    assert state.add_waiting_prompt_fields(dict(result), include_kind=False)["question"] == "Continue?"
    result = add_waiting_prompt_fields(result, state, include_kind=False)

    assert result == {
        "task_id": "t3",
        "status": "waiting",
        "token_totals": {"prompt_tokens": 3, "completion_tokens": 4},
        "question": "Continue?",
        "options": ["Yes", "No"],
        "tool_name": "ask",
        "method": "",
    }


def test_peek_waiting_prompt_prefers_waiting_snapshot_without_queue_mutation():
    state = GatewayTaskState(task_id="t3b")
    state.waiting_prompt = {"question": "Snapshot prompt", "options": ["Go"], "tool_name": "ask"}
    state.question_queue.put({"question": "Queued prompt", "options": ["Stop"], "tool_name": "bash"})

    assert state.peek_waiting_prompt() == {
        "question": "Snapshot prompt",
        "options": ["Go"],
        "tool_name": "ask",
        "method": "",
    }
    assert state.question_queue.qsize() == 1


def test_task_actions_reply_and_cancel_preserve_waiting_semantics():
    state = GatewayTaskState(task_id="t4")
    state.status = "waiting"

    assert state.is_waiting_for_reply() is True
    assert is_waiting_for_reply(state) is True

    state.enqueue_reply("local")
    assert state.reply_queue.get_nowait() == "local"
    enqueue_reply(state, "yes")
    assert state.reply_queue.get_nowait() == "yes"

    state.cancel()
    assert state.reply_queue.get_nowait() == "__CANCELLED__"

    state.cancel_event.clear()
    cancel_task_state(state)
    assert state.cancel_event.is_set() is True
    assert state.reply_queue.get_nowait() == "__CANCELLED__"


def test_task_actions_cancel_non_waiting_does_not_enqueue_cancel_message():
    state = GatewayTaskState(task_id="t5")
    state.status = "running"

    assert state.is_waiting_for_reply() is False
    assert is_waiting_for_reply(state) is False

    state.cancel()
    assert state.reply_queue.empty() is True

    state.cancel_event.clear()
    cancel_task_state(state)
    assert state.cancel_event.is_set() is True
    assert state.reply_queue.empty() is True
