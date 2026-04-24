"""Phase 2 TDD: loop.py learner auto-trigger test."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from hermit_agent.loop import AgentLoop, _STATIC_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# System prompt nudge
# ---------------------------------------------------------------------------

def test_system_prompt_contains_skills_guidance():
    """System prompt must include a skill self-learning nudge."""
    assert "5" in _STATIC_SYSTEM_PROMPT  # Mention of 5+ tool calls
    assert "skill" in _STATIC_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# _tool_call_count counter
# ---------------------------------------------------------------------------

def test_agent_loop_has_tool_call_count():
    """AgentLoop must have a _tool_call_count attribute."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[])
    assert hasattr(agent, "_tool_call_count")
    assert agent._tool_call_count == 0


def test_tool_call_count_resets_on_new_run(tmp_path):
    """_tool_call_count must be reset to 0 when calling a new run_loop."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 7  # Accumulated value from previous session
    agent._reset_tool_call_count()
    assert agent._tool_call_count == 0


# ---------------------------------------------------------------------------
# Auto-trigger
# ---------------------------------------------------------------------------

def test_maybe_trigger_learner_fires_above_threshold(tmp_path):
    """If _tool_call_count >= 5, learner must be called."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 6
    agent.messages = [{"role": "user", "content": "Task request"}]

    with patch("hermit_agent.learner.Learner") as MockLearner:
        mock_instance = MockLearner.return_value
        mock_instance.extract_from_success.return_value = {
            "name": "test_skill",
            "description": "test",
            "triggers": ["test"],
            "rule": "rule",
            "why": "reason",
            "good_pattern": "good",
            "bad_pattern": "bad",
        }
        mock_instance.save_auto_learned.return_value = "/tmp/test_skill.md"

        agent._maybe_trigger_learner()

        mock_instance.extract_from_success.assert_called_once_with(
            agent.messages, 6
        )
        mock_instance.save_auto_learned.assert_called_once()


def test_maybe_trigger_learner_skips_below_threshold(tmp_path):
    """If _tool_call_count < 5, learner must not be called."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 3
    agent.messages = []

    with patch("hermit_agent.learner.Learner") as MockLearner:
        agent._maybe_trigger_learner()
        MockLearner.assert_not_called()


def test_maybe_trigger_learner_resets_count_after_fire(tmp_path):
    """_tool_call_count must be reset to 0 after trigger."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 5
    agent.messages = []

    with patch("hermit_agent.learner.Learner") as MockLearner:
        mock_instance = MockLearner.return_value
        mock_instance.extract_from_success.return_value = None

        agent._maybe_trigger_learner()
        assert agent._tool_call_count == 0


def test_maybe_trigger_learner_silent_on_exception(tmp_path):
    """The session must not be interrupted when a learner exception occurs."""
    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 5
    agent.messages = []

    with patch("hermit_agent.learner.Learner") as MockLearner:
        MockLearner.side_effect = Exception("LLM connection error")
        # Exception must not be propagated
        agent._maybe_trigger_learner()  # should not raise
