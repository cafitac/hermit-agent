"""MetricsAggregator — session JSONL aggregation + guardrail removal/addition suggestions.

Read source: ~/.hermit/metrics/sessions/*.jsonl
Each JSONL follows session.jsonl format (contains type/kind/gid fields).

Three signals:
  1. trigger_frequency — G# trigger frequency (low → removal candidate)
  2. completion_rate   — session completion rate (low → addition needed signal)
  3. correction_rate   — user correction frequency (high → addition needed signal)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_SESSIONS_DIR = Path.home() / ".hermit" / "metrics" / "sessions"

# Removal candidate: trigger_freq == 0 AND completion_rate >= 0.8
_REMOVAL_TRIGGER_THRESHOLD = 0.0   # G# triggered 0 times
_REMOVAL_COMPLETION_MIN = 0.8      # completion rate >= 80%

# Addition candidate: completion_rate < 0.6 OR correction_rate > 0.3
_ADDITION_COMPLETION_MAX = 0.6
_ADDITION_CORRECTION_MIN = 0.3


@dataclass
class SessionStats:
    session_id: str
    model: str = "unknown"
    success: bool = False
    termination: str = ""
    compact_count: int = 0
    test_pass_count: int = 0
    test_fail_count: int = 0
    loop_reentry_count: int = 0
    guardrail_triggers: list[str] = field(default_factory=list)   # gid list
    user_corrections: int = 0


def _parse_session(path: Path) -> SessionStats | None:
    """Parse a single session JSONL → SessionStats."""
    sid = path.stem
    stats = SessionStats(session_id=sid)
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "attachment":
                    continue
                kind = rec.get("kind", "")
                if kind == "session_outcome":
                    stats.model = rec.get("model", "unknown")
                    stats.success = bool(rec.get("success", False))
                    stats.termination = rec.get("termination", "")
                    stats.compact_count = int(rec.get("compact_count", 0))
                    stats.test_pass_count = int(rec.get("test_pass_count", 0))
                    stats.test_fail_count = int(rec.get("test_fail_count", 0))
                    stats.loop_reentry_count = int(rec.get("loop_reentry_count", 0))
                elif kind == "guardrail_trigger":
                    gid = rec.get("gid", "")
                    if gid:
                        stats.guardrail_triggers.append(gid)
                elif kind == "user_correction":
                    stats.user_corrections += 1
    except Exception:
        return None
    return stats


class MetricsAggregator:
    """Session aggregation + guardrail suggestion calculation."""

    def __init__(self, sessions_dir: Path | str | None = None):
        self._sessions_dir = Path(sessions_dir) if sessions_dir else _SESSIONS_DIR

    def load_sessions(self, min_sessions: int = 1) -> list[SessionStats]:
        """Parse session JSONL files and return a list of SessionStats."""
        if not self._sessions_dir.exists():
            return []
        sessions = []
        for p in sorted(self._sessions_dir.glob("*.jsonl")):
            s = _parse_session(p)
            if s is not None:
                sessions.append(s)
        return sessions

    def trigger_frequency(self, sessions: list[SessionStats], gid: str) -> float:
        """G# trigger frequency (ratio of sessions where the gid fired)."""
        if not sessions:
            return 0.0
        fired = sum(1 for s in sessions if gid in s.guardrail_triggers)
        return fired / len(sessions)

    def completion_rate(self, sessions: list[SessionStats]) -> float:
        """Session completion rate."""
        if not sessions:
            return 0.0
        return sum(1 for s in sessions if s.success) / len(sessions)

    def correction_rate(self, sessions: list[SessionStats]) -> float:
        """User correction frequency (average corrections per session)."""
        if not sessions:
            return 0.0
        return sum(s.user_corrections for s in sessions) / len(sessions)

    def trigger_counts(self, sessions: list[SessionStats]) -> dict[str, int]:
        """Aggregate G# → trigger count."""
        counts: dict[str, int] = {}
        for s in sessions:
            for gid in s.guardrail_triggers:
                counts[gid] = counts.get(gid, 0) + 1
        return counts

    def removal_candidates(
        self, sessions: list[SessionStats], known_gids: list[str]
    ) -> list[str]:
        """Removal candidate G# list.

        Condition: trigger frequency == 0 AND completion rate >= 0.8
        """
        if not sessions:
            return []
        cr = self.completion_rate(sessions)
        if cr < _REMOVAL_COMPLETION_MIN:
            return []
        candidates = []
        for gid in known_gids:
            if self.trigger_frequency(sessions, gid) <= _REMOVAL_TRIGGER_THRESHOLD:
                candidates.append(gid)
        return candidates

    def addition_signals(self, sessions: list[SessionStats]) -> dict:
        """Return signals that may indicate a guardrail addition is needed.

        Completion rate < 0.6 or correction rate > 0.3 suggests review is needed.
        """
        cr = self.completion_rate(sessions)
        corr = self.correction_rate(sessions)
        return {
            "completion_rate": cr,
            "correction_rate": corr,
            "needs_review": cr < _ADDITION_COMPLETION_MAX or corr > _ADDITION_CORRECTION_MIN,
        }

    def summarize(self, sessions: list[SessionStats]) -> dict:
        """Overall aggregation summary."""
        return {
            "total_sessions": len(sessions),
            "completion_rate": self.completion_rate(sessions),
            "correction_rate": self.correction_rate(sessions),
            "trigger_counts": self.trigger_counts(sessions),
            "avg_compact_count": (
                sum(s.compact_count for s in sessions) / len(sessions) if sessions else 0.0
            ),
            "avg_test_fail_count": (
                sum(s.test_fail_count for s in sessions) / len(sessions) if sessions else 0.0
            ),
        }


__all__ = ["MetricsAggregator", "SessionStats"]
