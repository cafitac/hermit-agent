"""Step 1 TDD: HookEvent.ON_STOP exists and is fired during shutdown."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from hermit_agent.hooks import HookEvent


def test_on_stop_event_exists():
    """HookEvent must have ON_STOP member."""
    assert hasattr(HookEvent, "ON_STOP")
    assert HookEvent.ON_STOP.value == "OnStop"


def test_shutdown_fires_on_stop_hook(tmp_path):
    """AgentLoop.shutdown() must fire ON_STOP hook exactly once."""
    from hermit_agent.loop import AgentLoop

    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))

    # Replace hook_runner with a mock to capture calls
    mock_runner = MagicMock()
    agent.hook_runner = mock_runner

    agent.shutdown()

    # Find the ON_STOP call among all run_hooks calls
    on_stop_calls = [
        c for c in mock_runner.run_hooks.call_args_list
        if c[0][0] == HookEvent.ON_STOP
    ]
    assert len(on_stop_calls) == 1


def test_shutdown_fires_on_stop_with_session_metadata(tmp_path):
    """ON_STOP hook must receive session_id, model_id, tool_call_count."""
    from hermit_agent.loop import AgentLoop

    llm = MagicMock()
    llm.model_id = "test-model"
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 7

    mock_runner = MagicMock()
    agent.hook_runner = mock_runner

    agent.shutdown()

    on_stop_calls = [
        c for c in mock_runner.run_hooks.call_args_list
        if c[0][0] == HookEvent.ON_STOP
    ]
    assert len(on_stop_calls) == 1
    payload = on_stop_calls[0][0][2]  # third positional arg
    assert payload["session_id"] == agent.session_id
    assert payload["model_id"] == "test-model"
    assert payload["tool_call_count"] == 7
