"""US-006: Unit tests for hermit_agent/llm/base.py parsing logic."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


# ─── TokenUsage ──────────────────────────────────────────────────────────────


def test_token_usage_accumulate_basic():
    from hermit_agent.llm.types import TokenUsage

    usage = TokenUsage()
    usage.accumulate({"prompt_tokens": 100, "completion_tokens": 50})
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 50
    assert usage.total == 150


def test_token_usage_accumulate_multiple():
    from hermit_agent.llm.types import TokenUsage

    usage = TokenUsage()
    usage.accumulate({"prompt_tokens": 100, "completion_tokens": 50})
    usage.accumulate({"prompt_tokens": 200, "completion_tokens": 80})
    assert usage.prompt_tokens == 300
    assert usage.completion_tokens == 130
    assert usage.total == 430


def test_token_usage_accumulate_cached_tokens():
    from hermit_agent.llm.types import TokenUsage

    usage = TokenUsage()
    usage.accumulate({
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 60},
    })
    assert usage.cached_tokens == 60


def test_token_usage_accumulate_reasoning_tokens():
    from hermit_agent.llm.types import TokenUsage

    usage = TokenUsage()
    usage.accumulate({
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "completion_tokens_details": {"reasoning_tokens": 30},
    })
    assert usage.reasoning_tokens == 30


def test_token_usage_accumulate_missing_keys():
    from hermit_agent.llm.types import TokenUsage

    usage = TokenUsage()
    usage.accumulate({})
    assert usage.total == 0


# ─── LLMResponse ─────────────────────────────────────────────────────────────


def test_llm_response_has_tool_calls_true():
    from hermit_agent.llm.types import LLMResponse, ToolCall

    tc = ToolCall(id="call_1", name="bash", arguments={"command": "ls"})
    resp = LLMResponse(content=None, tool_calls=[tc])
    assert resp.has_tool_calls is True


def test_llm_response_has_tool_calls_false():
    from hermit_agent.llm.types import LLMResponse

    resp = LLMResponse(content="hello")
    assert resp.has_tool_calls is False


# ─── Tool call parsing from non-streaming response ───────────────────────────


def _make_client():
    from hermit_agent.llm.openai_compat import OpenAICompatClient
    return OpenAICompatClient(base_url="http://fake-llm", model="test-model")


def _fake_chat_response(content=None, tool_calls=None, usage=None):
    msg = {}
    if content is not None:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_parse_tool_calls_from_openai_response():
    """chat() correctly parses tool_call arguments from JSON string."""
    client = _make_client()
    fake_resp = _fake_chat_response(
        tool_calls=[{
            "id": "call_abc",
            "function": {
                "name": "bash",
                "arguments": '{"command": "echo hi"}',
            },
        }]
    )
    with patch("hermit_agent.llm.base.httpx.Client") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_response

        result = client.chat([{"role": "user", "content": "hi"}])

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "bash"
    assert result.tool_calls[0].arguments == {"command": "echo hi"}


def test_parse_response_without_tool_calls():
    """chat() handles a plain text response with no tool_calls."""
    client = _make_client()
    fake_resp = _fake_chat_response(content="Hello world")
    with patch("hermit_agent.llm.base.httpx.Client") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_response

        result = client.chat([{"role": "user", "content": "hi"}])

    assert result.content == "Hello world"
    assert result.tool_calls == []


def test_tool_call_with_invalid_json_arguments_returns_empty_dict():
    """chat() handles malformed JSON in tool_call arguments gracefully."""
    client = _make_client()
    fake_resp = _fake_chat_response(
        tool_calls=[{
            "id": "call_bad",
            "function": {
                "name": "bash",
                "arguments": "{invalid json!!!}",
            },
        }]
    )
    with patch("hermit_agent.llm.base.httpx.Client") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_response

        result = client.chat([{"role": "user", "content": "hi"}])

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {}


# ─── Streaming tool_call accumulator ─────────────────────────────────────────


def test_parse_streaming_tool_call_accumulator():
    """chat_stream() assembles fragmented tool_call deltas into a ToolCall."""
    client = _make_client()

    sse_lines = [
        'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "bash", "arguments": ""}}]}}]}),
        'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"command":'}}]}}]}),
        'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "ls"}'}}]}}]}),
        'data: ' + json.dumps({"choices": [{"delta": {}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
        'data: [DONE]',
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.iter_lines.return_value = iter(sse_lines)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("hermit_agent.llm.base.httpx.Client") as mock_client_cls:
        mock_http = MagicMock()
        mock_http.stream.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_http

        gen = client.chat_stream([{"role": "user", "content": "hi"}])
        chunks = []
        try:
            while True:
                chunks.append(next(gen))
        except StopIteration as e:
            final = e.value

    tool_call_done = [c for c in chunks if c.type == "tool_call_done"]
    assert len(tool_call_done) == 1
    assert tool_call_done[0].tool_call.name == "bash"
    assert tool_call_done[0].tool_call.arguments == {"command": "ls"}
    assert final.tool_calls[0].arguments == {"command": "ls"}
