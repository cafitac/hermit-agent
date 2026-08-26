from __future__ import annotations

import json


def test_mcp_server_exposes_only_the_task_lifecycle_tools() -> None:
    from hermit_agent.mcp_server import SERVER_INSTRUCTIONS, TOOLS

    assert [tool["name"] for tool in TOOLS] == ["run_task", "reply_task", "check_task", "cancel_task"]
    run_task = TOOLS[0]
    assert run_task["inputSchema"]["required"] == ["task", "cwd"]
    assert "background" not in run_task["inputSchema"]["properties"]
    assert run_task["inputSchema"]["properties"]["strategy"]["enum"] == ["single", "auto"]
    assert "bounded implementation" in SERVER_INSTRUCTIONS


def test_mcp_server_serializes_results_without_escaping_korean() -> None:
    from hermit_agent.mcp_server import _result_to_text

    result = _result_to_text({"status": "done", "result": "작업 완료"})

    assert json.loads(result) == {"status": "done", "result": "작업 완료"}


def test_mcp_server_uses_gateway_settings(monkeypatch) -> None:
    from hermit_agent import mcp_server

    sentinel = object()
    monkeypatch.setattr(
        mcp_server,
        "init_gateway_client",
        lambda **kwargs: ("http://gateway.test", "token", sentinel),
    )

    mcp_server._init_gateway_client()

    assert mcp_server._GATEWAY_URL == "http://gateway.test"
    assert mcp_server._GATEWAY_API_KEY == "token"
    assert mcp_server._GATEWAY_CLIENT is sentinel
    assert mcp_server._gateway_headers() == {"Content-Type": "application/json", "Authorization": "Bearer token"}
