"""G38b — Abort with text_loop when the same text content is repeated 3 consecutive times."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.llm_client import OllamaClient, LLMResponse, StreamChunk, ToolCall
from hermit_agent.loop import AgentLoop
from hermit_agent.permissions import PermissionMode
from hermit_agent.tools import create_default_tools


class _ScriptedLLM(OllamaClient):
    def __init__(self, responses: list[LLMResponse]):
        self.model = "stub"
        self._responses = list(responses)
        self.calls: list = []

    def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0) if self._responses else LLMResponse(content=None, tool_calls=[])

    def chat_stream(self, *args, **kwargs):
        r = self.chat(*args, **kwargs)
        if r.content:
            yield StreamChunk(type="text", text=r.content)
        for tc in r.tool_calls:
            yield StreamChunk(type="tool_call_done", tool_call=tc)
        yield StreamChunk(type="done")


def _make_agent(cwd: str, llm: OllamaClient) -> AgentLoop:
    agent = AgentLoop(
        llm=llm,
        tools=create_default_tools(cwd=cwd),
        cwd=cwd,
        permission_mode=PermissionMode.YOLO,
    )
    agent._context_injected = True  # Skip classification call (scripted LLM)
    return agent


def test_same_text_with_tool_calls_5_times_triggers_text_loop():
    """Abort with text_loop if the same text is repeated 5 consecutive times with different tool_calls.

    Since tool_calls are different each time, tool_loop detection is not triggered.
    text_loop should trigger as long as only the text content is the same.
    Threshold: _text_repeat_count >= 5 (6 turns required since the first turn is initialization)
    """
    with tempfile.TemporaryDirectory() as tmp:
        repeated_text = "Same message repeated"
        # Make bash commands different each time to prevent tool_loop detection
        llm = _ScriptedLLM([
            LLMResponse(content=repeated_text, tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo 1"})]),
            LLMResponse(content=repeated_text, tool_calls=[ToolCall(id="c2", name="bash", arguments={"command": "echo 2"})]),
            LLMResponse(content=repeated_text, tool_calls=[ToolCall(id="c3", name="bash", arguments={"command": "echo 3"})]),
            LLMResponse(content=repeated_text, tool_calls=[ToolCall(id="c4", name="bash", arguments={"command": "echo 4"})]),
            LLMResponse(content=repeated_text, tool_calls=[ToolCall(id="c5", name="bash", arguments={"command": "echo 5"})]),
            LLMResponse(content=repeated_text, tool_calls=[ToolCall(id="c6", name="bash", arguments={"command": "echo 6"})]),
            LLMResponse(content="Done", tool_calls=[]),  # Safety net — should not be reached
        ])
        agent = _make_agent(tmp, llm)
        result = agent.run("Start task")

        assert agent.last_termination == "text_loop", (
            f"expected 'text_loop', got '{agent.last_termination}'. result={result!r}"
        )
        # Safety net (completion) must not be reached
        assert len(llm.calls) <= 6, f"too many LLM calls: {len(llm.calls)}"


def test_different_text_each_turn_does_not_trigger_text_loop():
    """If the text is different every turn, text_loop is not detected."""
    with tempfile.TemporaryDirectory() as tmp:
        def bash_call(tool_id: str) -> ToolCall:
            return ToolCall(id=tool_id, name="bash", arguments={"command": "echo ok"})
        llm = _ScriptedLLM([
            LLMResponse(content="First message", tool_calls=[bash_call("c1")]),
            LLMResponse(content="Second message", tool_calls=[bash_call("c2")]),
            LLMResponse(content="Third message", tool_calls=[bash_call("c3")]),
            LLMResponse(content="Completed", tool_calls=[]),
        ])
        agent = _make_agent(tmp, llm)
        result = agent.run("Start task")

        assert agent.last_termination != "text_loop", (
            f"false positive: text_loop triggered. result={result!r}"
        )
        assert "Completed" in result or "Done" in result, f"expected completion, got {result!r}"


def test_text_loop_state_resets_between_runs():
    """The text_loop detection state is reset on consecutive run() calls."""
    with tempfile.TemporaryDirectory() as tmp:
        llm = _ScriptedLLM([
            # 1st run: normal completion (different text)
            LLMResponse(content="Working", tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo 1"})]),
            LLMResponse(content="Done", tool_calls=[]),
            # 2nd run: same text + different tool_calls → text_loop detected (threshold 5)
            LLMResponse(content="Repeating", tool_calls=[ToolCall(id="c2", name="bash", arguments={"command": "echo 2"})]),
            LLMResponse(content="Repeating", tool_calls=[ToolCall(id="c3", name="bash", arguments={"command": "echo 3"})]),
            LLMResponse(content="Repeating", tool_calls=[ToolCall(id="c4", name="bash", arguments={"command": "echo 4"})]),
            LLMResponse(content="Repeating", tool_calls=[ToolCall(id="c5", name="bash", arguments={"command": "echo 5"})]),
            LLMResponse(content="Repeating", tool_calls=[ToolCall(id="c6", name="bash", arguments={"command": "echo 6"})]),
            LLMResponse(content="Repeating", tool_calls=[ToolCall(id="c7", name="bash", arguments={"command": "echo 7"})]),
        ])
        agent = _make_agent(tmp, llm)

        result1 = agent.run("First request")
        assert agent.last_termination != "text_loop", f"1st run should not trigger text_loop: {result1}"

        result2 = agent.run("Second request")
        assert agent.last_termination == "text_loop", (
            f"2nd run should trigger text_loop, got '{agent.last_termination}'. result={result2!r}"
        )
