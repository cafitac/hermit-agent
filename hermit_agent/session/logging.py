from __future__ import annotations


def attach_session_logger(*, llm, agent, mode: str, cwd: str, session_id: str, parent_session_id: str | None = None) -> None:
    """Attach SessionLogger to the active llm/emitter pair for a session."""
    from .logger import SessionLogger
    from .store import SessionStore

    store = SessionStore()
    session_dir = store.create_session(
        mode=mode,
        session_id=session_id,
        cwd=cwd,
        parent_session_id=parent_session_id,
    )
    logger = SessionLogger(session_dir=session_dir)
    llm.session_logger = logger
    if agent is not None and hasattr(agent, "emitter"):
        agent.emitter.session_logger = logger
