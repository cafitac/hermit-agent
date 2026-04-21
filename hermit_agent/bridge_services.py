from __future__ import annotations


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


def submit_bridge_task(
    *,
    client,
    task: str,
    cwd: str,
    model: str,
    max_turns: int,
    parent_session_id: str,
    build_gateway_task_request,
) -> dict:
    return client.create_task_payload(
        **build_gateway_task_request(
            task=task,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            parent_session_id=parent_session_id,
        )
    )
