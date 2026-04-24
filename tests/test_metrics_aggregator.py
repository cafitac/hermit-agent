"""MetricsAggregator unit tests (Phase 2)."""

import json
import tempfile
from pathlib import Path

import pytest

from hermit_agent.metrics.aggregator import MetricsAggregator, _parse_session


# ── Helpers ──────────────────────────────────────────────────────

def _write_session(sessions_dir: Path, session_id: str, records: list[dict]) -> Path:
    """Create a test session JSONL file."""
    path = sessions_dir / f"{session_id}.jsonl"
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


def _outcome_record(success: bool, model: str = "test-model", **kwargs) -> dict:
    return {
        "type": "attachment",
        "kind": "session_outcome",
        "model": model,
        "success": success,
        "termination": "completed" if success else "max_turns",
        "compact_count": kwargs.get("compact_count", 0),
        "test_pass_count": kwargs.get("test_pass_count", 0),
        "test_fail_count": kwargs.get("test_fail_count", 0),
        "loop_reentry_count": kwargs.get("loop_reentry_count", 0),
    }


def _trigger_record(gid: str, reason: str = "") -> dict:
    return {
        "type": "attachment",
        "kind": "guardrail_trigger",
        "gid": gid,
        "reason": reason,
    }


def _correction_record(message: str = "no that's not right", pattern: str = "no") -> dict:
    return {
        "type": "attachment",
        "kind": "user_correction",
        "content": message,
        "pattern": pattern,
    }


# ── _parse_session tests ──────────────────────────────────────

def test_parse_session_success():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "abc123.jsonl"
        _write_session(Path(tmp), "abc123", [
            _outcome_record(True, model="qwen3-coder:30b", compact_count=2, test_pass_count=3),
            _trigger_record("G26"),
            _trigger_record("G38"),
            _correction_record(),
        ])
        stats = _parse_session(p)
        assert stats is not None
        assert stats.session_id == "abc123"
        assert stats.success is True
        assert stats.model == "qwen3-coder:30b"
        assert stats.compact_count == 2
        assert stats.test_pass_count == 3
        assert "G26" in stats.guardrail_triggers
        assert "G38" in stats.guardrail_triggers
        assert stats.user_corrections == 1


def test_parse_session_missing_file():
    stats = _parse_session(Path("/nonexistent/session.jsonl"))
    assert stats is None


def test_parse_session_malformed_lines():
    """Parses valid lines even if the JSONL contains broken lines."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "x.jsonl"
        with open(p, "w") as f:
            f.write("not-json\n")
            f.write(json.dumps(_outcome_record(False)) + "\n")
        stats = _parse_session(p)
        assert stats is not None
        assert stats.success is False


# ── MetricsAggregator tests ──────────────────────────────────

@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    return tmp_path


def _populate_sessions(sessions_dir: Path, n_success: int, n_fail: int, triggers: list[str] | None = None) -> list[Path]:
    paths = []
    for i in range(n_success):
        recs = [_outcome_record(True)]
        for gid in (triggers or []):
            recs.append(_trigger_record(gid))
        p = _write_session(sessions_dir, f"success_{i}", recs)
        paths.append(p)
    for i in range(n_fail):
        p = _write_session(sessions_dir, f"fail_{i}", [_outcome_record(False)])
        paths.append(p)
    return paths


def test_load_sessions_empty(sessions_dir: Path):
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    assert agg.load_sessions() == []


def test_load_sessions_basic(sessions_dir: Path):
    _populate_sessions(sessions_dir, n_success=3, n_fail=2)
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    assert len(sessions) == 5


def test_completion_rate(sessions_dir: Path):
    _populate_sessions(sessions_dir, n_success=8, n_fail=2)
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    assert abs(agg.completion_rate(sessions) - 0.8) < 0.01


def test_completion_rate_empty():
    agg = MetricsAggregator()
    assert agg.completion_rate([]) == 0.0


def test_trigger_frequency(sessions_dir: Path):
    # G26 triggered in 4 out of 10 sessions
    for i in range(4):
        _write_session(sessions_dir, f"trig_{i}", [
            _outcome_record(True),
            _trigger_record("G26"),
        ])
    for i in range(6):
        _write_session(sessions_dir, f"notrig_{i}", [_outcome_record(True)])
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    freq = agg.trigger_frequency(sessions, "G26")
    assert abs(freq - 0.4) < 0.01


def test_trigger_frequency_zero(sessions_dir: Path):
    _populate_sessions(sessions_dir, n_success=5, n_fail=0)
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    assert agg.trigger_frequency(sessions, "G99") == 0.0


def test_correction_rate(sessions_dir: Path):
    # 2 corrections each in 2 sessions
    for i in range(2):
        _write_session(sessions_dir, f"corr_{i}", [
            _outcome_record(True),
            _correction_record(),
            _correction_record(),
        ])
    for i in range(3):
        _write_session(sessions_dir, f"nocorr_{i}", [_outcome_record(True)])
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    # Total 4 corrections / 5 sessions = 0.8
    assert abs(agg.correction_rate(sessions) - 0.8) < 0.01


def test_removal_candidates_found(sessions_dir: Path):
    """Triggered 0 times + completion rate ≥ 80% → removal candidate."""
    # All 10 sessions successful, G26 not triggered
    _populate_sessions(sessions_dir, n_success=10, n_fail=0, triggers=["G38"])
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    candidates = agg.removal_candidates(sessions, ["G26", "G38"])
    assert "G26" in candidates   # Triggered 0 times
    assert "G38" not in candidates  # Triggered


def test_removal_candidates_low_completion(sessions_dir: Path):
    """No removal candidates if completion rate is low."""
    _populate_sessions(sessions_dir, n_success=5, n_fail=5)  # 50%
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    candidates = agg.removal_candidates(sessions, ["G26"])
    assert candidates == []


def test_addition_signals_normal(sessions_dir: Path):
    _populate_sessions(sessions_dir, n_success=9, n_fail=1)
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    signals = agg.addition_signals(sessions)
    assert signals["needs_review"] is False


def test_addition_signals_low_completion(sessions_dir: Path):
    _populate_sessions(sessions_dir, n_success=4, n_fail=6)  # 40%
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    signals = agg.addition_signals(sessions)
    assert signals["needs_review"] is True


def test_summarize(sessions_dir: Path):
    _populate_sessions(sessions_dir, n_success=7, n_fail=3, triggers=["G26"])
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    summary = agg.summarize(sessions)
    assert summary["total_sessions"] == 10
    assert abs(summary["completion_rate"] - 0.7) < 0.01
    assert summary["trigger_counts"].get("G26", 0) == 7


def test_trigger_counts(sessions_dir: Path):
    _write_session(sessions_dir, "s1", [
        _outcome_record(True),
        _trigger_record("G26"),
        _trigger_record("G26"),
        _trigger_record("G38"),
    ])
    _write_session(sessions_dir, "s2", [
        _outcome_record(True),
        _trigger_record("G38"),
    ])
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()
    counts = agg.trigger_counts(sessions)
    assert counts["G26"] == 2
    assert counts["G38"] == 2
