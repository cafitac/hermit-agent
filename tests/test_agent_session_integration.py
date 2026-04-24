import os
from unittest.mock import MagicMock

from hermit_agent.session_store import cwd_slug


def test_cli_agent_session_setup_logger_uses_session_store(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.agent_session import CLIAgentSession
    from hermit_agent.permissions import PermissionMode
    llm = MagicMock()
    llm.model = 'm'
    llm.session_logger = None
    test_cwd = str(tmp_path / 'work')
    os.makedirs(test_cwd, exist_ok=True)
    sess = CLIAgentSession(llm=llm, cwd=test_cwd, permission_mode=PermissionMode.ALLOW_READ)
    sess._setup_agent()
    sess._setup_session_logger()
    assert sess.llm.session_logger is not None
    expected_root = tmp_path / '.hermit' / 'logs' / 'single' / cwd_slug(test_cwd)
    assert any(expected_root.glob('*/meta.json'))


def test_mcp_agent_session_accepts_parent_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.agent_session import MCPAgentSession
    import inspect
    sig = inspect.signature(MCPAgentSession.__init__)
    assert 'parent_session_id' in sig.parameters, 'MCPAgentSession.__init__ must accept parent_session_id'
