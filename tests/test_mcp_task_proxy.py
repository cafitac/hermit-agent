from __future__ import annotations

from unittest.mock import MagicMock

from hermit_agent.mcp_task_proxy import MCPGatewayProxy


def _make_proxy(response_payload: dict):
    client = MagicMock()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = response_payload
    client.post.return_value = response
    client.get.return_value = response
    client.delete.return_value = response
    calls = {}
    def notify_channel(*args, **kwargs):
        calls["notify_channel"] = {"args": args, "kwargs": kwargs}

    proxy = MCPGatewayProxy(
        gateway_url="http://localhost:8765",
        gateway_client=client,
        gateway_headers=lambda: {"Authorization": "Bearer token"},
        start_sse_bridge=lambda task_id: calls.setdefault("start_sse_bridge", task_id),
        cleanup_sse_bridge=lambda task_id: calls.setdefault("cleanup_sse_bridge", task_id),
        notify_error=lambda task_id, message: calls.setdefault("notify_error", (task_id, message)),
        notify_reply=lambda task_id, message: calls.setdefault("notify_reply", (task_id, message)),
        notify_channel=notify_channel,
        truncate_result=lambda result: (f"truncated:{result}", {"truncated": True}),
        remember_task_context=lambda task_id, cwd: calls.setdefault("remember_task_context", (task_id, cwd)),
    )
    return proxy, client, calls


def test_proxy_run_task_starts_sse_bridge_for_running_tasks():
    proxy, client, calls = _make_proxy({"task_id": "task-1", "status": "running"})

    result = proxy.run_task(task="hello", cwd="/tmp", model="", max_turns=3)

    assert result == {"status": "running", "task_id": "task-1"}
    assert calls["remember_task_context"] == ("task-1", "/tmp")
    assert calls["start_sse_bridge"] == "task-1"
    client.post.assert_called_once()


def test_proxy_check_task_notifies_waiting_and_truncates_done():
    proxy, _client, calls = _make_proxy({"status": "waiting", "kind": "permission_ask", "tool_name": "bash", "method": "item/permissions/requestApproval", "question": "Continue?", "options": ["Yes", "No"]})
    waiting = proxy.check_task(task_id="task-1", full=False)
    assert waiting["status"] == "waiting"
    assert calls["notify_channel"] == {
        "args": ("task-1", "Continue?", ["Yes", "No"]),
        "kwargs": {"prompt_kind": "permission_ask", "tool_name": "bash", "method": "item/permissions/requestApproval"},
    }

    proxy, _client, calls = _make_proxy({"status": "done", "result": "full text"})
    done = proxy.check_task(task_id="task-2", full=False)
    assert done["result"] == "truncated:full text"
    assert done["_truncation"] == {"truncated": True}


def test_proxy_reply_and_cancel_return_running_and_cancelled():
    proxy, _client, calls = _make_proxy({})

    assert proxy.reply_task(task_id="task-1", message="yes") == {"status": "running", "task_id": "task-1"}
    assert calls["notify_reply"] == ("task-1", "yes")

    assert proxy.cancel_task(task_id="task-1") == {"status": "cancelled", "task_id": "task-1"}
    assert calls["cleanup_sse_bridge"] == "task-1"
