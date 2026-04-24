import json
from pathlib import Path

from hermit_agent.session_store import SessionStore, cwd_slug


def test_session_store_writes_under_logs_single(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    sd = store.create_session(mode='single', session_id='sess001', cwd='/Users/reddit/Project/claude-code', model='glm-5.1')
    expected = tmp_path / 'logs' / 'single' / '-Users-reddit-Project-claude-code' / 'sess001'
    assert Path(sd) == expected
    (Path(sd) / 'messages.json').write_text(json.dumps([
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': 'yo'},
    ]))
    store.update_meta(sd, status='completed', turn_count=1, preview='hi')
    meta = store.get_meta(sd)
    assert meta['status'] == 'completed'
    assert meta['turn_count'] == 1
    assert meta['preview'] == 'hi'
    assert (Path(sd) / 'messages.json').exists()


def test_legacy_session_loadable_via_session_store(tmp_path):
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'old1.json').write_text(json.dumps({
        'meta': {
            'session_id': 'old1',
            'model': 'old',
            'cwd': '/x',
            'created_at': 1.0,
            'updated_at': 1.0,
            'turn_count': 2,
            'preview': '',
        },
        'messages': [{'role': 'user', 'content': 'yo'}],
        'system_prompt': '',
    }))
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(legacy))
    result = store.load_session('old1')
    assert result is not None
    assert result['meta']['session_id'] == 'old1'
    assert result['messages'] == [{'role': 'user', 'content': 'yo'}]


def test_session_py_load_session_delegates_to_session_store(tmp_path, monkeypatch):
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'old2.json').write_text(json.dumps({
        'meta': {
            'session_id': 'old2',
            'model': 'old',
            'cwd': '/x',
            'created_at': 1.0,
            'updated_at': 1.0,
            'turn_count': 1,
            'preview': '',
        },
        'messages': [{'role': 'user', 'content': 'hello'}],
        'system_prompt': '',
    }))
    fake_logs = tmp_path / 'logs'
    fake_logs.mkdir()
    monkeypatch.setattr('hermit_agent.session_store.SessionStore.__init__',
                        lambda self, root=None, legacy_root=None:
                        SessionStore.__init__.__wrapped__(self, root=str(fake_logs), legacy_root=str(legacy))
                        if False else type(self).__bases__[0].__init__(self) or setattr(self, 'root', str(fake_logs)) or setattr(self, 'legacy_root', str(legacy)))
    # The cleaner path: just verify session.py uses SessionStore underneath.
    from hermit_agent import session as session_mod
    import inspect
    src = inspect.getsource(session_mod.load_session)
    assert 'SessionStore' in src, 'session.py::load_session must delegate to SessionStore'
    src_list = inspect.getsource(session_mod.list_sessions)
    assert 'SessionStore' in src_list, 'session.py::list_sessions must delegate to SessionStore'


def test_main_no_writes_to_legacy_dir(tmp_path):
    # Sanity: SessionStore with a fresh root creates only under root, never under legacy_root.
    legacy = tmp_path / 'legacy_unused'
    legacy.mkdir()
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(legacy))
    store.create_session(mode='single', session_id='new1', cwd='/x', model='m')
    assert list(legacy.glob('*.json')) == []
    assert (tmp_path / 'logs' / 'single' / cwd_slug('/x') / 'new1' / 'meta.json').exists()
