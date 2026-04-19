import datetime
import json
import os
import time
import pytest


def _seed(store, mode, sid, cwd, turn_count, updated_at):
    sd = store.create_session(mode=mode, session_id=sid, cwd=cwd)
    store.update_meta(sd, turn_count=turn_count)
    # Force the updated_at field to a known value (override the auto-bump
    # done by update_meta).
    meta_path = os.path.join(sd, 'meta.json')
    meta = json.loads(open(meta_path).read())
    meta['updated_at'] = updated_at
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    return sd


def test_should_auto_recap_true_when_stale_and_long(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import should_auto_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    one_hour_ago = (datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _seed(store, 'tui', 'old', '/x', turn_count=10, updated_at=one_hour_ago)
    assert should_auto_recap('/x', store=store) is True


def test_should_auto_recap_false_when_recent(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import should_auto_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    five_min_ago = (datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _seed(store, 'tui', 'recent', '/x', turn_count=10, updated_at=five_min_ago)
    assert should_auto_recap('/x', store=store) is False


def test_should_auto_recap_false_when_too_few_turns(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import should_auto_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    one_hour_ago = (datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _seed(store, 'tui', 'short', '/x', turn_count=3, updated_at=one_hour_ago)
    assert should_auto_recap('/x', store=store) is False


def test_should_auto_recap_disabled_via_settings(tmp_path, monkeypatch):
    settings_path = tmp_path / '.hermit' / 'settings.json'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({'auto_recap': False}))
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import should_auto_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    one_hour_ago = (datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _seed(store, 'tui', 'old', '/x', turn_count=10, updated_at=one_hour_ago)
    assert should_auto_recap('/x', store=store) is False


def test_should_auto_recap_respects_custom_threshold(tmp_path, monkeypatch):
    settings_path = tmp_path / '.hermit' / 'settings.json'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({'auto_recap_minutes': 120}))
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import should_auto_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    one_hour_ago = (datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    _seed(store, 'tui', 'old', '/x', turn_count=10, updated_at=one_hour_ago)
    # Threshold 120 min, age 60 min → False
    assert should_auto_recap('/x', store=store) is False


def test_should_auto_recap_no_qualifying_session(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import should_auto_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    assert should_auto_recap('/x', store=store) is False
