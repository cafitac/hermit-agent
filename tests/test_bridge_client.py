from __future__ import annotations

from unittest.mock import MagicMock


def test_interactive_session_client_methods_use_internal_routes():
    from hermit_agent.bridge_client import GatewayClient

    client = GatewayClient("http://localhost:8765", "token")
    create_response = MagicMock()
    create_response.json.return_value = {"session_id": "interactive-1", "status": "active"}
    create_response.raise_for_status.return_value = None
    send_response = MagicMock()
    send_response.json.return_value = {"session_id": "interactive-1", "status": "running"}
    send_response.raise_for_status.return_value = None
    client._client = MagicMock()
    status_response = MagicMock()
    status_response.json.return_value = {"session_id": "interactive-1", "status": "active"}
    status_response.raise_for_status.return_value = None
    client._client.post.side_effect = [create_response, send_response]
    client._client.get.return_value = status_response

    try:
        session = client.create_interactive_session_payload(
            cwd="/tmp",
            model="__auto__",
            parent_session_id="parent-1",
        )
        turn = client.send_interactive_message("interactive-1", "hello")
        status = client.get_interactive_session("interactive-1")
    finally:
        client.close()

    assert session == {"session_id": "interactive-1", "status": "active"}
    assert turn == {"session_id": "interactive-1", "status": "running"}
    assert status == {"session_id": "interactive-1", "status": "active"}
    assert client._client.post.call_args_list[0].args[0].endswith("/internal/interactive-sessions")
    assert client._client.post.call_args_list[1].args[0].endswith("/internal/interactive-sessions/interactive-1/messages")
    assert client._client.get.call_args.args[0].endswith("/internal/interactive-sessions/interactive-1")
