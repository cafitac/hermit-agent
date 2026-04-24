import os
from unittest.mock import MagicMock
from hermit_agent.learner import Learner


def test_learner_default_root_is_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm = MagicMock()
    llm.model = 'm'
    learner = Learner(llm=llm)
    assert learner.root == str(tmp_path)
    assert learner.auto_learned_dir == os.path.join(str(tmp_path), '.hermit', 'skills', 'auto-learned')
    assert learner.pending_dir.startswith(str(tmp_path))


def test_learner_explicit_root(tmp_path):
    llm = MagicMock()
    llm.model = 'm'
    learner = Learner(llm=llm, root=str(tmp_path / 'subproject'))
    assert learner.root == str(tmp_path / 'subproject')


def test_learner_save_writes_under_root(tmp_path):
    llm = MagicMock()
    llm.model = 'm'
    learner = Learner(llm=llm, root=str(tmp_path))
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


def test_maybe_trigger_learner_skips_gateway(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from hermit_agent.loop import AgentLoop
    from hermit_agent.permissions import PermissionMode
    llm = MagicMock()
    llm.model = 'm'
    loop = AgentLoop(llm=llm, tools=[], cwd=str(tmp_path), permission_mode=PermissionMode.ALLOW_READ, session_kind='gateway')
    # Call the trigger — should return silently without creating any .hermit/skills/auto-learned dir
    loop._maybe_trigger_learner()
    assert not os.path.exists(os.path.join(str(tmp_path), '.hermit', 'skills', 'auto-learned'))
