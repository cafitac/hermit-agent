"""/recap skill — produce a plain-text summary of the most recent multi-turn
session for a given cwd, optionally chained with linked gateway sub-sessions.

Reads via SessionStore.list_sessions / load_session. Output is plain text
(no markdown rendering required).
"""
from __future__ import annotations
import datetime
import json
import os
from typing import Optional

from ...session_store import SessionStore


_MIN_TURN_COUNT = 3
_MAX_GATEWAY_LINKS = 5


def generate_recap(cwd: str, store: Optional[SessionStore] = None) -> str:
    """Return a plain-text recap of the most recent qualifying session for cwd.

    Picks the most recent session (any mode) for the given cwd whose
    turn_count >= 3. If none qualifies, returns 'No recent session found.'

    For TUI sessions, also lists linked gateway sub-sessions
    (parent_session_id = TUI session_id) up to _MAX_GATEWAY_LINKS.
    """
    store = store or SessionStore()
    sessions = store.list_sessions(cwd=cwd, limit=20)
    qualifying = [s for s in sessions if s.get('turn_count', 0) >= _MIN_TURN_COUNT]
    if not qualifying:
        return 'No recent session found.'

    sess = qualifying[0]
    sess_id = sess.get('session_id', '?')
    mode = sess.get('mode', '?')
    turn_count = sess.get('turn_count', 0)
    preview = sess.get('preview', '') or ''
    updated_at = sess.get('updated_at', '?')
    model = sess.get('model', '?') or '?'

    lines = [
        f'Most recent session: {sess_id}',
        f'  mode: {mode}',
        f'  model: {model}',
        f'  cwd: {cwd}',
        f'  turns: {turn_count}',
        f'  updated_at: {updated_at}',
        f'  preview: {preview[:200]}',
    ]

    if mode == 'tui':
        gateway_subs = store.list_sessions(
            mode='gateway', cwd=cwd, limit=_MAX_GATEWAY_LINKS, parent_session_id=sess_id,
        )
        if gateway_subs:
            lines.append('')
            lines.append(f'Linked gateway calls ({len(gateway_subs)}):')
            for g in gateway_subs:
                lines.append(
                    f"  - task {g.get('session_id', '?')}: "
                    f"status={g.get('status', '?')} turns={g.get('turn_count', 0)}"
                )

    return '\n'.join(lines)


class RecapSkill:
    """Object form for callers that prefer a class-based interface."""

    def __init__(self, store: Optional[SessionStore] = None):
        self._store = store

    def run(self, cwd: str) -> str:
        return generate_recap(cwd, store=self._store)


def _ensure_dt(value):
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=datetime.timezone.utc,
            )
        except ValueError:
            return None
    return None


def _load_settings_for_recap():
    path = os.path.expanduser('~/.hermit/settings.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def should_auto_recap(cwd: str, threshold_minutes: int = 30, store: Optional[SessionStore] = None,
                      now: Optional[datetime.datetime] = None) -> bool:
    cfg = _load_settings_for_recap()
    if cfg.get('auto_recap', True) is False:
        return False
    threshold_minutes = int(cfg.get('auto_recap_minutes', threshold_minutes))

    store = store or SessionStore()
    sessions = store.list_sessions(cwd=cwd, limit=5)
    qualifying = [s for s in sessions if s.get('turn_count', 0) >= 5]
    if not qualifying:
        return False
    latest = qualifying[0]
    updated_at = _ensure_dt(latest.get('updated_at'))
    if updated_at is None:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age_minutes = (now - updated_at).total_seconds() / 60.0
    return age_minutes > threshold_minutes
