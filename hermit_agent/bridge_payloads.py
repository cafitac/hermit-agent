from __future__ import annotations


def build_ready_payload(*, model: str, cwd: str, version: str, commands: dict[str, str]) -> dict:
    return {
        "type": "ready",
        "model": model,
        "session_id": "gateway",
        "cwd": cwd,
        "permission": "accept_edits",
        "version": version,
        "commands": commands,
    }


def build_interactive_session_request(
    *,
    cwd: str,
    model: str,
    parent_session_id: str,
    session_id: str | None = None,
) -> dict:
    payload: dict = {
        "cwd": cwd,
        "model": model,
        "parent_session_id": parent_session_id,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


def build_interactive_message_request(*, message: str) -> dict:
    return {"message": message}
