from __future__ import annotations

from hermit_agent.gateway.routes.tasks import _peek_waiting_prompt
from hermit_agent.gateway.task_store import GatewayTaskState


def test_peek_waiting_prompt_returns_question_and_preserves_queue():
    state = GatewayTaskState(task_id="t1")
    prompt = {"question": "Allow?", "options": ["Yes", "No"]}
    state.question_queue.put(prompt)

    result = _peek_waiting_prompt(state)

    assert result == prompt
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
    if state.status == "waiting":
        result.update(_peek_waiting_prompt(state))
        result["kind"] = state.waiting_kind or "waiting"

    assert result == {
        "task_id": "t2",
        "status": "waiting",
        "result": None,
        "token_totals": {"prompt_tokens": 1, "completion_tokens": 2},
        "question": "[Permission request] bash",
        "options": ["Yes (once)", "No"],
        "kind": "permission_ask",
    }
