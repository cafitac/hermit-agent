"""G36 — Messages of the in-progress turn must be removed from the context upon interrupt. Current bug: Previous tool_use/tool_result/assistant messages remain in self.messages even after an interrupt, causing the next /command execution to start in a polluted state. Phase information/tool results from previous sessions accumulate in the new session. Expected behavior: Upon interrupt, maintain only up to the last completed turn (= right before the last user message). The user message of the interrupted turn + subsequent assistant/tool messages must all be removed."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.llm_client import OllamaClient
from hermit_agent.loop import AgentLoop
from hermit_agent.permissions import PermissionMode
from hermit_agent.tools import create_default_tools


class _StubLLM(OllamaClient):
    def __init__(self):
        self.model = "stub"


def _make_agent(cwd: str) -> AgentLoop:
    return AgentLoop(
        llm=_StubLLM(),
        tools=create_default_tools(cwd=cwd),
        cwd=cwd,
        permission_mode=PermissionMode.YOLO,
    )


def test_interrupt_drops_in_flight_turn_keeping_prior_history():
    """Upon interrupt handling, remove only the messages of the in-progress turn and keep previous completed turns."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        # Completed past turn: user → assistant(text)
        agent.messages = [
            {"role": "user", "content": "prior finished request"},
            {"role": "assistant", "content": "here's my prior answer"},
            # Interrupted in-progress turn: user → assistant(tool_call) → tool_result
            {"role": "user", "content": "interrupted request"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_x",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_x", "content": "some output"},
        ]
        agent.reset_after_interrupt()
        assert len(agent.messages) == 2, agent.messages
        assert agent.messages[0]["role"] == "user"
        assert agent.messages[0]["content"] == "prior finished request"
        assert agent.messages[1]["role"] == "assistant"


def test_interrupt_with_only_one_in_flight_turn_clears_all():
    """Completely initialize messages upon interrupt when there is only an in-progress turn."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        agent.messages = [
            {"role": "user", "content": "first command (interrupted)"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "x"},
        ]
        agent.reset_after_interrupt()
        assert agent.messages == [], agent.messages


def test_interrupt_with_no_pending_turn_is_noop():
    """Do nothing if the conversation is in an initial state (= started without a user message)."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        agent.messages = []
        agent.reset_after_interrupt()
        assert agent.messages == []


def test_interrupt_between_completed_turns_still_trims_last_user():
    """Remove the last user turn even if an interrupt occurs when the last turn has already been completed."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        agent.messages = [
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "turn 2 completed"},
            {"role": "assistant", "content": "reply 2"},
        ]
        agent.reset_after_interrupt()
        # All messages up to turn 2 are removed, leaving only turn 1
        assert len(agent.messages) == 2
        assert agent.messages[1]["content"] == "reply 1"
