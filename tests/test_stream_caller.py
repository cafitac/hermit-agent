"""US-002: Unit tests for StreamingCaller class."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_caller():
    from hermit_agent.stream_caller import StreamingCaller

    agent = SimpleNamespace(
        llm=MagicMock(),
        emitter=MagicMock(),
        token_totals={"prompt_tokens": 0, "completion_tokens": 0},
        interrupted=False,
        messages=[],
        system_prompt="sys",
        abort_event=MagicMock(),
    )
    agent._tool_schemas = MagicMock(return_value=[])
    return StreamingCaller(agent=agent), agent


def _text_chunk(text: str):
    return SimpleNamespace(type="text", text=text, tool_call=None)


def _usage_chunk(prompt: int, completion: int):
    chunk = SimpleNamespace(type="usage")
    chunk.usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    return chunk


def _tool_chunk(tool_call_obj):
    return SimpleNamespace(type="tool_call_done", tool_call=tool_call_obj)


def test_call_returns_response_with_text():
    """call() assembles text chunks into LLMResponse.content."""
    caller, agent = _make_caller()
    agent.llm.chat_stream.return_value = iter([
        _text_chunk("Hello"),
        _text_chunk(" world"),
    ])
    result = caller.call()
    assert result is not None
    assert result.content == "Hello world"
    assert result.tool_calls == []


def test_call_sets_interrupted_on_interrupted_error():
    """call() sets agent.interrupted=True and returns None on InterruptedError."""
    caller, agent = _make_caller()
    agent.llm.chat_stream.side_effect = InterruptedError
    result = caller.call()
    assert result is None
    assert agent.interrupted is True


def test_call_accumulates_token_usage():
    """call() adds usage counts to agent.token_totals."""
    caller, agent = _make_caller()
    agent.llm.chat_stream.return_value = iter([
        _usage_chunk(prompt=100, completion=50),
    ])
    caller.call()
    assert agent.token_totals["prompt_tokens"] == 100
    assert agent.token_totals["completion_tokens"] == 50
