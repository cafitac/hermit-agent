"""Phase 2→3 TDD: loop.py learner integration.

Phase 3 moves the WRITE path from _maybe_trigger_learner (in-process)
to OnStop hook → agent-learner Popen. The method is removed; these tests
verify the removal is intentional and the counter still exists for metadata.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from hermit_agent.loop import AgentLoop, _STATIC_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# System prompt nudge (kept)
# ---------------------------------------------------------------------------

def test_system_prompt_contains_skills_guidance():
    """System prompt must include a skill self-learning nudge."""
    assert "5" in _STATIC_SYSTEM_PROMPT  # Mention of 5+ tool calls
    assert "skill" in _STATIC_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# _tool_call_count counter (kept — used for ON_STOP metadata)
# ---------------------------------------------------------------------------

def test_agent_loop_has_tool_call_count():
    """AgentLoop must have a _tool_call_count attribute."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[])
    assert hasattr(agent, "_tool_call_count")
    assert agent._tool_call_count == 0


def test_tool_call_count_resets_on_new_run(tmp_path):
    """_tool_call_count must be reset to 0 when calling reset."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 7  # Accumulated value from previous session
    agent._reset_tool_call_count()
    assert agent._tool_call_count == 0


# ---------------------------------------------------------------------------
# WRITE path removal (Phase 3)
# ---------------------------------------------------------------------------

def test_maybe_trigger_learner_method_removed():
    """_maybe_trigger_learner method must no longer exist on AgentLoop."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[])
    assert not hasattr(agent, "_maybe_trigger_learner"), (
        "_maybe_trigger_learner was removed in Phase 3 (WRITE → OnStop hook)"
    )
