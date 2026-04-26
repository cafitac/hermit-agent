import json
import os
import time
from hermit_agent.session_store import SessionStore, cwd_slug, derive_preview, read_jsonl


def test_cwd_slug_basic():
    assert cwd_slug('/Users/reddit/Project/claude-code') == '-Users-reddit-Project-claude-code'


def test_cwd_slug_root():
    assert cwd_slug('/') == '-'


def test_cwd_slug_long_path_truncated_with_hash():
    s = cwd_slug('/' + 'x' * 250)
    assert len(s) <= 209
    assert '-' in s


def test_cwd_slug_collision_documented():
    assert cwd_slug('/foo-bar') == '-foo-bar'
    assert cwd_slug('/foo_bar') == '-foo-bar'


def test_create_session_writes_meta(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    sd = store.create_session(mode='single', session_id='abc123def456', cwd='/x/y', model='m1')
    assert os.path.isdir(sd)
    meta = json.loads(open(os.path.join(sd, 'meta.json')).read())
    assert meta['session_id'] == 'abc123def456'
    assert meta['mode'] == 'single'
    assert meta['cwd'] == '/x/y'
    assert meta['model'] == 'm1'
    assert meta['status'] == 'active'
    assert meta['parent_session_id'] is None
    assert meta['turn_count'] == 0
    assert meta['preview'] == ''
    assert 'created_at' in meta
    assert 'updated_at' in meta


def test_create_session_with_parent_id(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    sd = store.create_session(mode='gateway', session_id='t001', cwd='/x', parent_session_id='abc')
    assert store.get_meta(sd)['parent_session_id'] == 'abc'


def test_atomic_meta_write_no_tmp_left(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    sd = store.create_session(mode='tui', session_id='zzz', cwd='/x')
    store.update_meta(sd, status='completed', turn_count=5)
    files = os.listdir(sd)
    assert 'meta.json' in files
    assert not any(f.endswith('.tmp') for f in files)
    m = store.get_meta(sd)
    assert m['status'] == 'completed'
    assert m['turn_count'] == 5


def test_list_sessions_sorted_newest_first(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    store.create_session(mode='tui', session_id='a', cwd='/x')
    time.sleep(1.1)
    store.create_session(mode='tui', session_id='b', cwd='/x')
    time.sleep(1.1)
    a_dir = os.path.join(str(tmp_path / 'logs'), 'tui', cwd_slug('/x'), 'a')
    store.update_meta(a_dir, status='completed')
    out = store.list_sessions(mode='tui', cwd='/x')
    assert [s['session_id'] for s in out] == ['a', 'b']


def test_list_sessions_filter_parent_session_id(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    store.create_session(mode='gateway', session_id='t1', cwd='/x', parent_session_id='P')
    store.create_session(mode='gateway', session_id='t2', cwd='/x', parent_session_id='OTHER')
    store.create_session(mode='gateway', session_id='t3', cwd='/x', parent_session_id='P')
    out = store.list_sessions(mode='gateway', cwd='/x', parent_session_id='P')
    assert sorted(s['session_id'] for s in out) == ['t1', 't3']


def test_list_sessions_filter_by_cwd_uses_meta_not_slug(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    store.create_session(mode='tui', session_id='a', cwd='/foo-bar')
    store.create_session(mode='tui', session_id='b', cwd='/foo_bar')
    assert {s['session_id'] for s in store.list_sessions(mode='tui', cwd='/foo-bar')} == {'a'}
    assert {s['session_id'] for s in store.list_sessions(mode='tui', cwd='/foo_bar')} == {'b'}


def test_list_sessions_merges_legacy(tmp_path):
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'leg1.json').write_text(json.dumps({
        'meta': {
            'session_id': 'leg1',
            'model': 'old',
            'cwd': '/x',
            'created_at': time.time(),
            'updated_at': time.time(),
            'turn_count': 3,
            'preview': 'legacy',
        },
        'messages': [{'role': 'user', 'content': 'hi'}],
        'system_prompt': '',
    }))
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(legacy))
    store.create_session(mode='single', session_id='new1', cwd='/x')
    ids = {s['session_id'] for s in store.list_sessions(mode='single', cwd='/x')}
    assert 'leg1' in ids
    assert 'new1' in ids


def test_load_session_falls_back_to_legacy(tmp_path):
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'leg2.json').write_text(json.dumps({
        'meta': {
            'session_id': 'leg2',
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
    r = store.load_session('leg2')
    assert r is not None
    assert r['meta']['session_id'] == 'leg2'
    assert r['messages'] == [{'role': 'user', 'content': 'yo'}]


def test_load_session_returns_none_when_missing(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'empty'))
    assert store.load_session('nonexistent') is None


def test_jsonl_reader_skips_corrupt_last_line(tmp_path):
    p = tmp_path / 'events.jsonl'
    p.write_text('{"ok":1}\n{"ok":2}\n{"truncated"')
    assert read_jsonl(str(p)) == [{'ok': 1}, {'ok': 2}]


def test_write_messages_and_update_transcript_state_persist_preview_and_turn_count(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    sd = store.create_session(mode='interactive', session_id='i1', cwd='/x', model='m1')
    messages = [
        {'role': 'user', 'content': 'hello world'},
        {'role': 'assistant', 'content': 'hi'},
    ]

    path = store.write_messages(sd, messages)
    assert json.loads(open(path, encoding='utf-8').read()) == messages

    store.update_transcript_state(sd, messages=messages, turn_count=3, status='waiting')
    meta = store.get_meta(sd)
    assert meta['status'] == 'waiting'
    assert meta['turn_count'] == 3
    assert meta['preview'] == 'hello world'


def test_find_session_dir_and_derive_preview(tmp_path):
    store = SessionStore(root=str(tmp_path / 'logs'))
    sd = store.create_session(mode='interactive', session_id='sess-preview', cwd='/x/y')

    assert store.find_session_dir('sess-preview', mode='interactive', cwd='/x/y') == sd
    assert derive_preview([{'role': 'assistant', 'content': 'skip'}, {'role': 'user', 'content': 'pick me'}]) == 'pick me'


def test_derive_preview_strips_leading_context_blocks():
    content = (
        "<context>\nctx\n</context>\n\n"
        "<session-handoff>\nprev\n</session-handoff>\n\n"
        "actual user message"
    )
    assert derive_preview([{"role": "user", "content": content}]) == "actual user message"


# ─── US-003 shim contract ─────────────────────────────────────────────────────


def test_session_store_is_same_class_as_session_store_module():
    """session_store.SessionStore must be the exact same class as session.store.SessionStore."""
    from hermit_agent.session_store import SessionStore as ShimClass
    from hermit_agent.session.store import SessionStore as RealClass
    assert ShimClass is RealClass


def test_session_store_prune_mode_bucket_accessible(tmp_path):
    """SessionStore from shim must expose _prune_mode_bucket (session/store.py new method)."""
    from hermit_agent.session_store import SessionStore
    store = SessionStore(root=str(tmp_path / "logs"))
    assert hasattr(store, "_prune_mode_bucket"), "_prune_mode_bucket must be accessible via shim"
