import time


def _seed_session(store, mode, sid, cwd, turn_count, preview='', parent=None):
    sd = store.create_session(mode=mode, session_id=sid, cwd=cwd, parent_session_id=parent)
    store.update_meta(sd, turn_count=turn_count, preview=preview)
    return sd


def test_recap_no_qualifying_session_returns_message(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    out = generate_recap('/x', store=store)
    assert out == 'No recent session found.'


def test_recap_short_session_excluded(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    _seed_session(store, 'single', 'a', '/x', turn_count=2, preview='hi')
    out = generate_recap('/x', store=store)
    assert out == 'No recent session found.'


def test_recap_summarizes_most_recent(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    _seed_session(store, 'tui', 'older', '/x', turn_count=5, preview='older session')
    time.sleep(1.1)
    _seed_session(store, 'tui', 'newer', '/x', turn_count=7, preview='newer session topic')
    out = generate_recap('/x', store=store)
    assert 'newer' in out
    assert 'turns: 7' in out
    assert 'newer session topic' in out


def test_recap_excludes_other_cwd(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    _seed_session(store, 'tui', 'x_sess', '/x', turn_count=5, preview='x cwd')
    _seed_session(store, 'tui', 'y_sess', '/y', turn_count=10, preview='y cwd longer')
    out = generate_recap('/x', store=store)
    assert 'x_sess' in out
    assert 'y_sess' not in out


def test_recap_includes_linked_gateway_subsessions(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap
    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    _seed_session(store, 'tui', 'tui-parent', '/x', turn_count=4, preview='tui')
    _seed_session(store, 'gateway', 'gw-1', '/x', turn_count=1, parent='tui-parent')
    _seed_session(store, 'gateway', 'gw-2', '/x', turn_count=1, parent='tui-parent')
    _seed_session(store, 'gateway', 'gw-other', '/x', turn_count=1, parent='other-tui')
    out = generate_recap('/x', store=store)
    assert 'Linked gateway calls' in out
    assert 'gw-1' in out
    assert 'gw-2' in out
    assert 'gw-other' not in out


def test_recap_includes_linked_interactive_sessions_for_tui(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap

    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    _seed_session(store, 'interactive', 'ix-1', '/x', turn_count=6, preview='interactive one', parent='tui-parent')
    _seed_session(store, 'interactive', 'ix-2', '/x', turn_count=2, preview='interactive two', parent='tui-parent')
    _seed_session(store, 'interactive', 'ix-other', '/x', turn_count=9, preview='interactive other', parent='other-tui')
    time.sleep(1.1)
    _seed_session(store, 'tui', 'tui-parent', '/x', turn_count=4, preview='tui')

    out = generate_recap('/x', store=store)

    assert 'Linked interactive sessions' in out
    assert 'ix-1' in out
    assert 'ix-2' in out
    assert 'ix-other' not in out


def test_recap_interactive_session_shows_parent_tui(tmp_path):
    from hermit_agent.session_store import SessionStore
    from hermit_agent.skills.recap import generate_recap

    store = SessionStore(root=str(tmp_path / 'logs'), legacy_root=str(tmp_path / 'legacy'))
    _seed_session(store, 'tui', 'tui-parent', '/x', turn_count=3, preview='tui')
    _seed_session(store, 'interactive', 'ix-parented', '/x', turn_count=6, preview='interactive', parent='tui-parent')

    out = generate_recap('/x', store=store)

    assert 'mode: interactive' in out
    assert 'Parent TUI session: tui-parent' in out
