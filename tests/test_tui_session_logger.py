import json
from hermit_agent.session_logger import SessionLogger


def test_session_logger_does_not_truncate(tmp_path):
    session_dir = tmp_path / 'sess'
    session_dir.mkdir()
    events = session_dir / 'events.jsonl'
    events.write_text('{"existing":1}\n')
    SessionLogger(session_dir=str(session_dir))
    assert events.read_text() == '{"existing":1}\n'


def test_session_logger_writes_to_session_dir(tmp_path):
    session_dir = tmp_path / 'sess'
    session_dir.mkdir()
    logger = SessionLogger(session_dir=str(session_dir))
    logger.log_user('hello')
    events_path = session_dir / 'events.jsonl'
    assert events_path.exists()
    lines = [json.loads(line) for line in events_path.read_text().strip().split('\n') if line]
    assert any(rec.get('content') == 'hello' or rec.get('text') == 'hello' for rec in lines)


def test_session_logger_does_not_compute_paths(tmp_path):
    import inspect
    src = inspect.getsource(SessionLogger.__init__)
    assert 'cwd_slug' not in src
    assert 'expanduser' not in src


def test_two_loggers_use_different_dirs(tmp_path):
    sa = tmp_path / 'a'
    sb = tmp_path / 'b'
    sa.mkdir()
    sb.mkdir()
    la = SessionLogger(session_dir=str(sa))
    lb = SessionLogger(session_dir=str(sb))
    la.log_user('A')
    lb.log_user('B')
    text_a = (sa / 'events.jsonl').read_text()
    text_b = (sb / 'events.jsonl').read_text()
    assert 'A' in text_a and 'B' not in text_a
    assert 'B' in text_b and 'A' not in text_b
