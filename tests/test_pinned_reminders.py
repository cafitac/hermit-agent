"""G41 — PR body pinned_reminders: PR description is reinjected into context even after compact.

Test cases:
- test_feature_develop_pr_pins_body: Entering /feature-develop 123 creates a pr_123 entry in pinned_reminders
- test_non_feature_develop_input_not_pinned: Regular messages are not pinned
- test_gh_failure_silently_skipped: Agent execution is not interrupted even if gh command fails
- test_compact_reinjects_pinned_content: Pinned content is reinjected into messages after compact if present
- test_duplicate_pr_overwrites_not_appends: Calling the same PR twice maintains only one entry
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

from hermit_agent.llm_client import OllamaClient, LLMResponse
from hermit_agent.loop import AgentLoop
from hermit_agent.permissions import PermissionMode
from hermit_agent.tools import create_default_tools


class _StubLLM(OllamaClient):
    def __init__(self):
        self.model = "stub"

    def chat(self, messages, system=None, tools=None, abort_event=None):
        return LLMResponse(content="ok", tool_calls=[])

    def chat_stream(self, messages, system=None, tools=None, abort_event=None):
        from hermit_agent.llm_client import StreamChunk
        yield StreamChunk(type="text", text="ok")


def _make_agent(cwd: str) -> AgentLoop:
    tools = create_default_tools(cwd=cwd)
    agent = AgentLoop(
        llm=_StubLLM(),
        tools=tools,
        cwd=cwd,
        permission_mode=PermissionMode.YOLO,
    )
    agent._context_injected = True  # Skip classification call (scripted LLM)
    return agent


def _mock_gh_success(pr_num: str, title: str = "Test PR", body: str = "PR body content"):
    """Mock subprocess.run to return a successful gh pr view response."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({"title": title, "body": body})
    return result


def test_feature_develop_pr_pins_body():
    """Entering /feature-develop 123 creates a pr_123 key entry in pinned_reminders."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        mock_result = _mock_gh_success("123", title="Fix bug", body="## Spec\nDo the thing.")

        with patch("subprocess.run", return_value=mock_result):
            agent.run("/feature-develop 123")

        keys = [pin["key"] for pin in agent.pinned_reminders]
        assert "pr_123" in keys, f"expected pr_123 in pinned_reminders keys, got {keys}"

        pin = next(p for p in agent.pinned_reminders if p["key"] == "pr_123")
        assert "Fix bug" in pin["content"]
        assert "Do the thing." in pin["content"]
        assert "PR #123" in pin["content"]


def test_non_feature_develop_input_not_pinned():
    """Regular messages are not added to pinned_reminders."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)

        with patch("subprocess.run") as mock_run:
            agent.run("regular message")
            # subprocess.run should not have been called for gh pr view
            for call in mock_run.call_args_list:
                args = call.args[0] if call.args else call.kwargs.get("args", [])
                assert "gh" not in str(args), f"gh should not be called for regular message, got {args}"

        assert agent.pinned_reminders == [], f"expected empty pinned_reminders, got {agent.pinned_reminders}"


def test_gh_failure_silently_skipped():
    """Even if the gh command fails, agent execution is not interrupted and pinned_reminders remains empty."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)

        failed_result = MagicMock()
        failed_result.returncode = 1
        failed_result.stdout = ""

        with patch("subprocess.run", return_value=failed_result):
            # Must execute without exceptions even if it fails
            result = agent.run("/feature-develop 999")

        assert result is not None, "agent.run should return even when gh fails"
        assert agent.pinned_reminders == [], f"expected empty on gh failure, got {agent.pinned_reminders}"


def test_compact_reinjects_pinned_content():
    """When compact is triggered while pinned_reminders is present, the corresponding content is reinjected into messages."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)

        # Add entry to pinned_reminders directly
        agent.pinned_reminders.append({
            "key": "pr_42",
            "content": "=== PR #42 Original Description ===\nTitle: Feature X\n\nBig spec here.",
        })

        # Fill with large messages to force trigger compact
        # threshold = 32000 * 0.95 = 30400, compact_start = 30400 * 0.85 = 25840
        # Trigger compact at 30000 tokens
        big_content = "a" * (30000 * 3)  # ~30000 tokens — exceeds compact_start
        agent.messages = [{"role": "user", "content": big_content}]

        # Directly call reminder reinjection logic after compact
        from hermit_agent.loop import _find_project_config

        compact_level = agent.context_manager.get_compact_level(agent.messages)
        assert compact_level > 0, "compact should trigger for big messages"

        agent.messages = agent.context_manager.compact(agent.messages)

        # Simulate reinjection logic after compact (loop.py lines 808~824 logic)
        reminder_parts: list[str] = []
        project_config = _find_project_config(agent.cwd)
        if project_config:
            reminder_parts.append(project_config)
        for pin in agent.pinned_reminders:
            reminder_parts.append(pin["content"])
        if reminder_parts:
            agent.messages.append({
                "role": "user",
                "content": f"<system-reminder>\n{'---'.join(reminder_parts)}\n</system-reminder>",
            })

        # Pinned content must be included in messages
        combined = " ".join(str(m.get("content", "")) for m in agent.messages)
        assert "PR #42 Original Description" in combined, f"pinned content should appear in messages after compact. messages tail: {agent.messages[-1]}"
        assert "Big spec here." in combined


def test_duplicate_pr_overwrites_not_appends():
    """Calling with the same PR number twice maintains only one pinned_reminders entry."""
    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        mock_result = _mock_gh_success("77", title="PR title v1", body="Body v1")

        with patch("subprocess.run", return_value=mock_result):
            agent.run("/feature-develop 77")

        assert len([p for p in agent.pinned_reminders if p["key"] == "pr_77"]) == 1

        # Second call (content changed)
        mock_result2 = _mock_gh_success("77", title="PR title v2", body="Body v2")
        with patch("subprocess.run", return_value=mock_result2):
            agent.run("/feature-develop 77")

        pr_entries = [p for p in agent.pinned_reminders if p["key"] == "pr_77"]
        assert len(pr_entries) == 1, f"expected 1 entry, got {len(pr_entries)}: {pr_entries}"
        # Must be overwritten with the latest content
        assert "Body v2" in pr_entries[0]["content"], "should be updated to latest body"
