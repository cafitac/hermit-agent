"""Step 2 TDD: WRITE paths removed, agent-learner OnStop Popen wired."""
from __future__ import annotations

import pathlib
import subprocess
from unittest.mock import MagicMock, patch

from hermit_agent.hooks import HookEvent


# ---------------------------------------------------------------------------
# WRITE path removal: _maybe_trigger_learner gone from loop.py
# ---------------------------------------------------------------------------

def test_maybe_trigger_learner_removed_from_loop():
    """_maybe_trigger_learner method must no longer exist in loop.py."""
    src = pathlib.Path("hermit_agent/loop.py").read_text()
    assert "_maybe_trigger_learner" not in src, "_maybe_trigger_learner should be removed"


def test_trigger_learner_call_removed_from_loop():
    """No call to _maybe_trigger_learner in loop.py."""
    src = pathlib.Path("hermit_agent/loop.py").read_text()
    assert "trigger_learner" not in src, "trigger_learner references should be removed"


# ---------------------------------------------------------------------------
# WRITE path removal: learner parts removed from _schedule_teardown
# ---------------------------------------------------------------------------

def test_schedule_teardown_no_learner_import():
    """_schedule_teardown must not import Learner."""
    src = pathlib.Path("hermit_agent/agent_session.py").read_text()
    # Find _schedule_teardown method body
    in_method = False
    for line in src.splitlines():
        if "def _schedule_teardown" in line:
            in_method = True
            continue
        if in_method:
            if line.startswith("    def ") and "_schedule_teardown" not in line:
                break  # Next method — stop
            assert "from .learner import" not in line, (
                "_schedule_teardown should not import Learner"
            )
            assert "record_run" not in line, (
                "_schedule_teardown should not call record_run"
            )
            assert "run_verify_cmds" not in line, (
                "_schedule_teardown should not call run_verify_cmds"
            )


# ---------------------------------------------------------------------------
# agent-learner Popen on stop
# ---------------------------------------------------------------------------

def test_agent_learner_called_on_stop(tmp_path, monkeypatch):
    """shutdown() must call agent-learner process when installed."""
    from hermit_agent.loop import AgentLoop

    popen_calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            popen_calls.append(cmd)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/agent-learner")

    llm = MagicMock()
    llm.model_id = "test-model"
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent.shutdown()

    al_calls = [c for c in popen_calls if "agent-learner" in c[0]]
    assert len(al_calls) == 1
    assert "process" in al_calls[0]


def test_agent_learner_skip_if_not_installed(tmp_path, monkeypatch):
    """shutdown() must not fail when agent-learner is not installed."""
    from hermit_agent.loop import AgentLoop

    monkeypatch.setattr("shutil.which", lambda x: None)

    llm = MagicMock()
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent.shutdown()  # Should not raise


def test_agent_learner_uses_session_metadata(tmp_path, monkeypatch):
    """agent-learner process must receive --session-id, --model-id, --cwd."""
    from hermit_agent.loop import AgentLoop

    popen_calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            popen_calls.append(cmd)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/agent-learner")

    llm = MagicMock()
    llm.model_id = "test-model"
    agent = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path))
    agent._tool_call_count = 10
    agent.shutdown()

    al_calls = [c for c in popen_calls if "agent-learner" in c[0]]
    assert len(al_calls) == 1
    cmd = al_calls[0]
    assert "--session-id" in cmd
    assert "--model-id" in cmd
    assert "--cwd" in cmd
