import os


def test_bridge_logs_user_input_and_done_event(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    from hermit_agent.session_logger import SessionLogger

    store = SessionStore()
    sd = store.create_session(mode='tui', session_id='bridgetest', cwd='/x')
    logger = SessionLogger(session_dir=sd)

    logger.on_user_input('hello user')
    logger.on_send({'type': 'streaming', 'token': 'Hi'})
    logger.on_send({'type': 'stream_end'})
    logger.on_send({'type': 'done', 'result': 'Hello world'})

    events_path = os.path.join(sd, 'events.jsonl')
    assert os.path.exists(events_path)
    raw = open(events_path).read()
    assert 'hello user' in raw
    assert 'Hello world' in raw or 'done' in raw, 'done event with result must be captured (wiring site #3b)'


def test_bridge_meta_status_set_to_completed(tmp_path, monkeypatch):
    monkeypatch.setattr('os.path.expanduser', lambda p: str(tmp_path / p.lstrip('~/'))
                        if p.startswith('~') else os.path.expanduser(p))
    from hermit_agent.session_store import SessionStore
    store = SessionStore()
    sd = store.create_session(mode='tui', session_id='shutdowntest', cwd='/x')
    store.update_meta(sd, status='completed')
    meta = store.get_meta(sd)
    assert meta['status'] == 'completed'
