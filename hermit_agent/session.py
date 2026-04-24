"""Session save/restore — based on Claude Code's sessionHistory.ts pattern.

Saves conversation history to disk and resumes with --resume.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass

from .session_store import SessionStore

SESSION_DIR = os.path.expanduser("~/.hermit/sessions")
LATEST_LINK = os.path.join(SESSION_DIR, "latest.json")


@dataclass
class SessionMeta:
    session_id: str
    model: str
    cwd: str
    created_at: float
    updated_at: float
    turn_count: int
    preview: str  # preview of the first user message
    recap: str = ""  # LLM-generated session summary (saved async on completion)


@dataclass
class SavedSession:
    meta: SessionMeta
    messages: list[dict]
    system_prompt: str


# Legacy: retained for read-compat with old session files
def save_session(
    session_id: str,
    messages: list[dict],
    system_prompt: str,
    model: str,
    cwd: str,
    turn_count: int,
) -> str:
    """Save session to disk."""
    os.makedirs(SESSION_DIR, exist_ok=True)

    # Extract preview from the first user message
    preview = ""
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            preview = msg["content"][:80]
            break

    meta = SessionMeta(
        session_id=session_id,
        model=model,
        cwd=cwd,
        created_at=time.time(),
        updated_at=time.time(),
        turn_count=turn_count,
        preview=preview,
    )

    filepath = os.path.join(SESSION_DIR, f"{session_id}.json")

    with open(filepath, "w") as f:
        json.dump({
            "meta": asdict(meta),
            "messages": messages,
            "system_prompt": system_prompt,
        }, f, ensure_ascii=False, indent=2)

    # Update latest link
    with open(LATEST_LINK, "w") as f:
        json.dump({"session_id": session_id}, f)

    return filepath


def load_session(session_id: str | None = None) -> SavedSession | None:
    """Restore session. If session_id is None, loads the most recent session."""
    store = SessionStore()
    if session_id is None:
        if not os.path.exists(LATEST_LINK):
            return None
        with open(LATEST_LINK) as f:
            data = json.load(f)
        session_id = data.get("session_id")
        if not session_id:
            return None

    result = store.load_session(session_id)
    if result is None:
        return None

    raw_meta = result['meta']
    # Convert ISO timestamps back to epoch for SessionMeta compat
    from .session_store import _parse_updated_at
    created_at = _parse_updated_at(raw_meta) if isinstance(raw_meta.get('created_at'), str) else raw_meta.get('created_at', 0.0)
    updated_at = _parse_updated_at(raw_meta) if isinstance(raw_meta.get('updated_at'), str) else raw_meta.get('updated_at', 0.0)
    meta = SessionMeta(
        session_id=raw_meta['session_id'],
        model=raw_meta.get('model', ''),
        cwd=raw_meta.get('cwd', ''),
        created_at=created_at,
        updated_at=updated_at,
        turn_count=raw_meta.get('turn_count', 0),
        preview=raw_meta.get('preview', ''),
    )
    return SavedSession(
        meta=meta,
        messages=result.get('messages') or [],
        system_prompt=result.get('system_prompt', ''),
    )


def list_sessions(limit: int = 10) -> list[SessionMeta]:
    """List recent sessions."""
    store = SessionStore()
    raw_list = store.list_sessions(limit=limit)
    sessions: list[SessionMeta] = []
    for raw_meta in raw_list:
        from .session_store import _parse_updated_at
        created_at = _parse_updated_at(raw_meta) if isinstance(raw_meta.get('created_at'), str) else raw_meta.get('created_at', 0.0)
        updated_at = _parse_updated_at(raw_meta) if isinstance(raw_meta.get('updated_at'), str) else raw_meta.get('updated_at', 0.0)
        sessions.append(SessionMeta(
            session_id=raw_meta['session_id'],
            model=raw_meta.get('model', ''),
            cwd=raw_meta.get('cwd', ''),
            created_at=created_at,
            updated_at=updated_at,
            turn_count=raw_meta.get('turn_count', 0),
            preview=raw_meta.get('preview', ''),
            recap=raw_meta.get('recap', ''),
        ))
    return sessions


def delete_session(session_id: str) -> bool:
    """Delete a session."""
    filepath = os.path.join(SESSION_DIR, f"{session_id}.json")
    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False
