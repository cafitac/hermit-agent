from __future__ import annotations

from types import SimpleNamespace


def test_attach_session_logger_wires_llm_and_emitter(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "os.path.expanduser",
        lambda p: str(tmp_path / p.lstrip("~/")) if p.startswith("~") else p,
    )
    from hermit_agent.session_logging import attach_session_logger

    llm = SimpleNamespace()
    agent = SimpleNamespace(emitter=SimpleNamespace())

    attach_session_logger(
        llm=llm,
        agent=agent,
        mode="bridge",
        cwd="/tmp/project",
        session_id="sess-1",
        parent_session_id="parent-1",
    )

    assert hasattr(llm, "session_logger")
    assert agent.emitter.session_logger is llm.session_logger
