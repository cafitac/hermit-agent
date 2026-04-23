from __future__ import annotations

from hermit_agent.gateway.task_api import GatewayTaskAPI
from hermit_agent.gateway.task_store import GatewayTaskState


def test_task_api_reply_cancel_and_status_payload():
    api = GatewayTaskAPI()
    state = GatewayTaskState(task_id="task-1")
    state.status = "waiting"
    state.waiting_kind = "permission_ask"
    state.waiting_prompt = {"question": "Allow?", "options": ["Yes", "No"], "tool_name": "bash"}

    assert api.reply(state, "yes") == {"status": "ok", "task_id": "task-1"}
    assert state.reply_queue.get_nowait() == "yes"

    payload = api.status_payload(state, include_kind=True)
    assert payload["question"] == "Allow?"
    assert payload["kind"] == "permission_ask"
    assert payload["tool_name"] == "bash"

    assert api.cancel(state) == {"status": "cancelled", "task_id": "task-1"}
    assert state.cancel_event.is_set() is True
    assert state.reply_queue.get_nowait() == "__CANCELLED__"


def test_task_api_status_payload_for_done_task_includes_result():
    api = GatewayTaskAPI()
    state = GatewayTaskState(task_id="task-2")
    state.status = "done"
    state.result = "complete"

    assert api.status_payload(state, include_kind=False) == {
        "task_id": "task-2",
        "status": "done",
        "token_totals": {"prompt_tokens": 0, "completion_tokens": 0},
        "result": "complete",
    }
