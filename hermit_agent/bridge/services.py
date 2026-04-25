from __future__ import annotations

import datetime

from ..session_store import SessionStore


def resolve_display_model(*, requested_model: str, cwd: str, load_settings, get_primary_model) -> str:
    if requested_model != "__auto__":
        return requested_model
    cfg = load_settings(cwd=cwd)
    return get_primary_model(cfg, available_only=True) or get_primary_model(cfg) or "__auto__"


def load_auto_recap_text(*, cwd: str, should_auto_recap, generate_recap) -> str | None:
    if not should_auto_recap(cwd):
        return None
    recap_text = generate_recap(cwd)
    if recap_text and recap_text != "No recent session found.":
        return "[Auto-recap of last session]\n" + recap_text
    return None


def _ensure_dt(value):
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc,
            )
        except ValueError:
            return None
    return None


def find_resumable_interactive_session(
    *,
    cwd: str,
    store: SessionStore | None = None,
    now: datetime.datetime | None = None,
    fresh_minutes: int = 30,
) -> dict | None:
    """Return the latest resumable interactive session for cwd.

    Rules:
    - `active` / `waiting` sessions are resumable regardless of age.
    - `completed` sessions are resumable only when still recent.
    - requires a non-empty persisted transcript in `messages.json`.
    """
    store = store or SessionStore()
    now = now or datetime.datetime.now(datetime.timezone.utc)
    sessions = store.list_sessions(mode="interactive", cwd=cwd, limit=10)
    for meta in sessions:
        session_id = meta.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            continue
        loaded = store.load_session(session_id, mode="interactive", cwd=cwd)
        messages = (loaded or {}).get("messages") or []
        if not messages:
            continue
        status = str(meta.get("status") or "")
        if status in {"active", "waiting", "running"}:
            return meta
        if status == "completed":
            updated_at = _ensure_dt(meta.get("updated_at"))
            if updated_at is None:
                continue
            age_minutes = (now - updated_at).total_seconds() / 60.0
            if age_minutes <= fresh_minutes:
                return meta
    return None


def sync_tui_session_meta_from_interactive(
    *,
    store: SessionStore,
    tui_session_dir: str,
    interactive_session_id: str | None,
    cwd: str,
    status: str | None = None,
) -> None:
    """Mirror interactive transcript summary into the TUI session meta."""
    if not interactive_session_id:
        if status is not None:
            store.update_meta(tui_session_dir, status=status)
        return

    loaded = store.load_session(interactive_session_id, mode="interactive", cwd=cwd)
    if loaded is None:
        if status is not None:
            store.update_meta(tui_session_dir, status=status)
        return

    meta = loaded.get("meta") or {}
    fields = {
        "interactive_session_id": interactive_session_id,
        "turn_count": int(meta.get("turn_count", 0)),
        "preview": str(meta.get("preview", "") or ""),
    }
    if status is not None:
        fields["status"] = status
    store.update_meta(tui_session_dir, **fields)


def ensure_interactive_session(
    *,
    client,
    cwd: str,
    model: str,
    parent_session_id: str,
    build_interactive_session_request,
    session_id: str | None = None,
) -> dict:
    return client.create_interactive_session_payload(
        **build_interactive_session_request(
            cwd=cwd,
            model=model,
            parent_session_id=parent_session_id,
            session_id=session_id,
        )
    )


def fetch_interactive_session_status(*, client, session_id: str) -> dict:
    return client.get_interactive_session(session_id)


def submit_interactive_turn(
    *,
    client,
    session_id: str,
    message: str,
    build_interactive_message_request,
) -> dict:
    return client.send_interactive_message(
        session_id,
        **build_interactive_message_request(message=message),
    )
