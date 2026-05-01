import os
from unittest.mock import MagicMock

import pytest

from hermit_agent.learner import Learner


def _make_legacy_learner(*args, **kwargs):
    with pytest.warns(DeprecationWarning, match="hermit_agent\\.learner\\.Learner is deprecated"):
        return Learner(*args, **kwargs)


def test_learner_default_root_is_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm = MagicMock()
    llm.model = 'm'
    learner = _make_legacy_learner(llm=llm)
    assert learner.root == str(tmp_path)
    assert learner.auto_learned_dir == os.path.join(str(tmp_path), '.hermit', 'skills', 'auto-learned')
    assert learner.pending_dir.startswith(str(tmp_path))


def test_learner_explicit_root(tmp_path):
    llm = MagicMock()
    llm.model = 'm'
    learner = _make_legacy_learner(llm=llm, root=str(tmp_path / 'subproject'))
    assert learner.root == str(tmp_path / 'subproject')


def test_learner_save_writes_under_root(tmp_path):
    llm = MagicMock()
    llm.model = 'm'
    learner = _make_legacy_learner(llm=llm, root=str(tmp_path))
    sample = {'name': 'test_rule', 'description': 'x', 'body': 'y'}
    path = learner.save_auto_learned(sample)
    assert path is not None
    assert str(tmp_path) in path
    assert '.hermit/skills/auto-learned' in path


def test_learner_enabled_for_gateway_returns_false():
    from hermit_agent.learner import learner_enabled_for
    assert learner_enabled_for('gateway') is False
    assert learner_enabled_for('mcp') is False
    assert learner_enabled_for('cli') is True
    assert learner_enabled_for('tui') is True
    assert learner_enabled_for(None) is True


def test_agent_loop_session_kind_parameter():
    from hermit_agent.loop import AgentLoop
    from hermit_agent.permissions import PermissionMode
    import inspect
    sig = inspect.signature(AgentLoop.__init__)
    assert 'session_kind' in sig.parameters
    llm = MagicMock()
    llm.model = 'm'
    loop = AgentLoop(llm=llm, tools=[], cwd='/tmp', permission_mode=PermissionMode.ALLOW_READ, session_kind='gateway')
    assert loop.session_kind == 'gateway'


def test_agent_learner_on_stop_skips_gateway(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/agent-learner")
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: calls.append(cmd))
    from hermit_agent.loop import AgentLoop
    from hermit_agent.permissions import PermissionMode
    llm = MagicMock()
    llm.model = 'm'
    loop = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path), permission_mode=PermissionMode.ALLOW_READ, session_kind='gateway')
    loop._run_agent_learner_on_stop()
    al_calls = [c for c in calls if c and "agent-learner" in c[0]]
    assert al_calls == [], "gateway session should not trigger agent-learner"
