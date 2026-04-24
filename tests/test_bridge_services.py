from __future__ import annotations

from hermit_agent.bridge_services import (
    ensure_interactive_session,
    fetch_interactive_session_status,
    find_resumable_interactive_session,
    load_auto_recap_text,
    resolve_display_model,
    sync_tui_session_meta_from_interactive,
    submit_interactive_turn,
)


def test_resolve_display_model_uses_requested_model_when_explicit():
    result = resolve_display_model(
        requested_model="gpt-5.4",
        cwd="/tmp",
        load_settings=lambda cwd=None: {"model": "glm-5.1"},
        get_primary_model=lambda cfg, available_only=False: "glm-5.1",
    )
    assert result == "gpt-5.4"


def test_resolve_display_model_uses_primary_model_for_auto():
    result = resolve_display_model(
        requested_model="__auto__",
        cwd="/tmp",
        load_settings=lambda cwd=None: {"model": "glm-5.1"},
        get_primary_model=lambda cfg, available_only=False: "gpt-5.4" if available_only else "glm-5.1",
    )
    assert result == "gpt-5.4"


def test_load_auto_recap_text_filters_empty_marker():
    assert load_auto_recap_text(
        cwd="/tmp",
        should_auto_recap=lambda cwd: True,
        generate_recap=lambda cwd: "No recent session found.",
    ) is None
    assert load_auto_recap_text(
        cwd="/tmp",
        should_auto_recap=lambda cwd: True,
        generate_recap=lambda cwd: "Carry this forward",
    ) == "[Auto-recap of last session]\nCarry this forward"


def test_ensure_interactive_session_delegates_to_client_with_built_payload():
    class _Client:
        def __init__(self):
            self.payload = None

        def create_interactive_session_payload(self, **kwargs):
            self.payload = kwargs
            return {"session_id": "interactive-1", "status": "active"}

    client = _Client()
    result = ensure_interactive_session(
        client=client,
        cwd="/tmp",
        model="__auto__",
        parent_session_id="sess-1",
        session_id="interactive-1",
        build_interactive_session_request=lambda **kwargs: kwargs,
    )

    assert result == {"session_id": "interactive-1", "status": "active"}
    assert client.payload["cwd"] == "/tmp"
    assert client.payload["session_id"] == "interactive-1"


def test_submit_interactive_turn_delegates_to_client_with_built_payload():
    class _Client:
        def __init__(self):
            self.session_id = None
            self.payload = None

        def send_interactive_message(self, session_id, **kwargs):
            self.session_id = session_id
            self.payload = kwargs
            return {"session_id": session_id, "status": "running"}

    client = _Client()
    result = submit_interactive_turn(
        client=client,
        session_id="interactive-2",
        message="hello",
        build_interactive_message_request=lambda **kwargs: kwargs,
    )

    assert result == {"session_id": "interactive-2", "status": "running"}
    assert client.session_id == "interactive-2"
    assert client.payload == {"message": "hello"}


def test_fetch_interactive_session_status_delegates_to_client():
    class _Client:
        def get_interactive_session(self, session_id):
            return {"session_id": session_id, "status": "waiting"}

    assert fetch_interactive_session_status(client=_Client(), session_id="interactive-3") == {
        "session_id": "interactive-3",
        "status": "waiting",
    }


def test_find_resumable_interactive_session_prefers_active_and_recent_completed(tmp_path):
    from hermit_agent.session_store import SessionStore

    store = SessionStore(root=str(tmp_path / "logs"), legacy_root=str(tmp_path / "legacy"))

    waiting_dir = store.create_session(mode="interactive", session_id="waiting-1", cwd="/x")
    store.update_transcript_state(
        waiting_dir,
        messages=[{"role": "user", "content": "keep going"}],
        turn_count=2,
        status="waiting",
    )

    result = find_resumable_interactive_session(cwd="/x", store=store)
    assert result is not None
    assert result["session_id"] == "waiting-1"


def test_find_resumable_interactive_session_skips_stale_completed_without_messages(tmp_path):
    import datetime
    import json

    from hermit_agent.session_store import SessionStore

    store = SessionStore(root=str(tmp_path / "logs"), legacy_root=str(tmp_path / "legacy"))
    stale_dir = store.create_session(mode="interactive", session_id="completed-1", cwd="/x")
    store.update_meta(stale_dir, status="completed", turn_count=3, preview="old")

    fresh_dir = store.create_session(mode="interactive", session_id="completed-2", cwd="/x")
    store.update_transcript_state(
        fresh_dir,
        messages=[{"role": "user", "content": "recent transcript"}],
        turn_count=3,
        status="completed",
    )

    stale_meta = store.get_meta(stale_dir)
    stale_meta["updated_at"] = "2026-01-01T00:00:00Z"
    (tmp_path / "logs" / "interactive" / "-x" / "completed-1" / "meta.json").write_text(
        json.dumps(stale_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fresh_meta = store.get_meta(fresh_dir)
    fresh_meta["updated_at"] = "2026-01-01T00:00:00Z"
    (tmp_path / "logs" / "interactive" / "-x" / "completed-2" / "meta.json").write_text(
        json.dumps(fresh_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    now = datetime.datetime(2026, 1, 1, 0, 20, 0, tzinfo=datetime.timezone.utc)
    result = find_resumable_interactive_session(cwd="/x", store=store, now=now, fresh_minutes=10)
    assert result is None


def test_sync_tui_session_meta_from_interactive_copies_preview_turns_and_status(tmp_path):
    from hermit_agent.session_store import SessionStore

    store = SessionStore(root=str(tmp_path / "logs"), legacy_root=str(tmp_path / "legacy"))
    tui_dir = store.create_session(mode="tui", session_id="tui-1", cwd="/x")
    interactive_dir = store.create_session(mode="interactive", session_id="interactive-1", cwd="/x")
    store.update_transcript_state(
        interactive_dir,
        messages=[{"role": "user", "content": "resume me"}],
        turn_count=4,
        status="waiting",
    )

    sync_tui_session_meta_from_interactive(
        store=store,
        tui_session_dir=tui_dir,
        interactive_session_id="interactive-1",
        cwd="/x",
        status="completed",
    )

    meta = store.get_meta(tui_dir)
    assert meta["interactive_session_id"] == "interactive-1"
    assert meta["turn_count"] == 4
    assert meta["preview"] == "resume me"
    assert meta["status"] == "completed"
