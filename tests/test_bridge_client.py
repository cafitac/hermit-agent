from __future__ import annotations

from unittest.mock import MagicMock


def test_create_task_uses_full_payload_response():
    from hermit_agent.bridge_client import GatewayClient

    client = GatewayClient("http://localhost:8765", "token")
    response = MagicMock()
    response.json.return_value = {"task_id": "task-123", "status": "running"}
    response.raise_for_status.return_value = None
    client._client = MagicMock()
    client._client.post.return_value = response

    try:
        payload = client.create_task_payload(
            task="hello",
            cwd="/tmp",
            model="__auto__",
            max_turns=3,
            parent_session_id="parent-1",
        )
        task_id = client.create_task("hello", "/tmp", "__auto__", 3, parent_session_id="parent-1")
    finally:
        client.close()

    assert payload == {"task_id": "task-123", "status": "running"}
    assert task_id == "task-123"
    client._client.post.assert_called()
