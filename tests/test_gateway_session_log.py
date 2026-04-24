import json
import os
from unittest.mock import patch


def _expanduser_factory(tmp_path):
    """Create an expanduser that redirects ~ to tmp_path without recursion."""
    real_expanduser = os.path.expanduser
    def _expanduser(p):
        if isinstance(p, str) and p.startswith('~'):
            return str(tmp_path / p.lstrip('~/'))
        return real_expanduser(p)
    return _expanduser


def test_gateway_session_log_creates_meta_and_events(tmp_path):
    from hermit_agent.session_store import cwd_slug
    with patch('hermit_agent.session_store.os.path.expanduser', _expanduser_factory(tmp_path)):
        from hermit_agent.gateway.session_log import GatewaySessionLog
        GatewaySessionLog(task_id='t001', cwd='/x/y', model='glm-5.1')
        expected = tmp_path / '.hermit' / 'logs' / 'gateway' / cwd_slug('/x/y') / 't001'
        assert (expected / 'meta.json').exists()
        assert (expected / 'events.jsonl').exists()
        meta = json.loads((expected / 'meta.json').read_text())
        assert meta['mode'] == 'gateway'
        assert meta['session_id'] == 't001'
        assert meta['cwd'] == '/x/y'
        assert meta['status'] == 'active'
        assert meta['parent_session_id'] is None
        events = (expected / 'events.jsonl').read_text().strip().split('\n')
        parsed = [json.loads(line) for line in events if line]
        assert any(e.get('type') == 'start' for e in parsed)


def test_gateway_session_log_with_parent_session_id(tmp_path):
    with patch('hermit_agent.session_store.os.path.expanduser', _expanduser_factory(tmp_path)):
        from hermit_agent.gateway.session_log import GatewaySessionLog
        from hermit_agent.session_store import SessionStore
        log = GatewaySessionLog(task_id='t002', cwd='/x', model='m', parent_session_id='tui-abc')
        store = SessionStore()
        meta = store.get_meta(log.session_dir)
        assert meta['parent_session_id'] == 'tui-abc'


def test_gateway_session_log_completed_status(tmp_path):
    with patch('hermit_agent.session_store.os.path.expanduser', _expanduser_factory(tmp_path)):
        from hermit_agent.gateway.session_log import GatewaySessionLog
        from hermit_agent.session_store import SessionStore
        log = GatewaySessionLog(task_id='t003', cwd='/x', model='m')
        log.mark_completed({'prompt_tokens': 100, 'completion_tokens': 50})
        meta = SessionStore().get_meta(log.session_dir)
        assert meta['status'] == 'completed'
        events = open(os.path.join(log.session_dir, 'events.jsonl')).read().strip().split('\n')
        parsed = [json.loads(line) for line in events]
        assert any(e.get('type') == 'done' for e in parsed)


def test_gateway_session_log_crashed_status(tmp_path):
    with patch('hermit_agent.session_store.os.path.expanduser', _expanduser_factory(tmp_path)):
        from hermit_agent.gateway.session_log import GatewaySessionLog
        from hermit_agent.session_store import SessionStore
        log = GatewaySessionLog(task_id='t004', cwd='/x', model='m')
        log.mark_crashed('upstream 500')
        meta = SessionStore().get_meta(log.session_dir)
        assert meta['status'] == 'crashed'


def test_gateway_session_log_arbitrary_events(tmp_path):
    with patch('hermit_agent.session_store.os.path.expanduser', _expanduser_factory(tmp_path)):
        from hermit_agent.gateway.session_log import GatewaySessionLog
        log = GatewaySessionLog(task_id='t005', cwd='/x', model='m')
        log.write_event({'type': 'tool_use', 'tool_name': 'bash'})
        log.write_event({'type': 'tool_result', 'is_error': False})
        events = open(os.path.join(log.session_dir, 'events.jsonl')).read().strip().split('\n')
        parsed = [json.loads(line) for line in events]
        assert any(e.get('type') == 'tool_use' for e in parsed)
        assert any(e.get('type') == 'tool_result' for e in parsed)
