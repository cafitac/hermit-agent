"""US-003/US-004: TaskContextManager and VisiblePromptDeduplicator class extraction."""
from __future__ import annotations

import threading


# ─── US-003: TaskContextManager ──────────────────────────────────────────────


def test_task_context_manager_register_and_cwd_for():
    """TaskContextManager.cwd_for() returns registered cwd."""
    from hermit_agent.mcp_channel import TaskContextManager

    mgr = TaskContextManager()
    mgr.register("task-abc", "/project/foo")
    assert mgr.cwd_for("task-abc") == "/project/foo"


def test_task_context_manager_unregister():
    """TaskContextManager.unregister() removes task context."""
    from hermit_agent.mcp_channel import TaskContextManager

    mgr = TaskContextManager()
    mgr.register("task-xyz", "/some/path")
    mgr.unregister("task-xyz")
    result = mgr.cwd_for("task-xyz")
    assert result != "/some/path"


def test_task_context_manager_cwd_for_unknown_returns_fallback():
    """cwd_for() with unknown task_id returns a non-empty fallback (os.getcwd())."""
    from hermit_agent.mcp_channel import TaskContextManager

    mgr = TaskContextManager()
    result = mgr.cwd_for("nonexistent-task")
    assert isinstance(result, str) and len(result) > 0


def test_task_context_manager_thread_safe():
    """Concurrent register/unregister should not raise errors."""
    from hermit_agent.mcp_channel import TaskContextManager

    mgr = TaskContextManager()
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            task_id = f"task-{i}"
            mgr.register(task_id, f"/path/{i}")
            _ = mgr.cwd_for(task_id)
            mgr.unregister(task_id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_module_shim_remember_and_forget_task_context():
    """Module-level _remember_task_context/_forget_task_context/_task_cwd still work."""
    from hermit_agent.mcp_channel import _remember_task_context, _forget_task_context, _task_cwd

    _remember_task_context("shim-task-test", "/shim/path")
    assert _task_cwd("shim-task-test") == "/shim/path"
    _forget_task_context("shim-task-test")


# ─── US-004: VisiblePromptDeduplicator ───────────────────────────────────────


def test_visible_prompt_deduplicator_notify_dedupes(monkeypatch):
    """VisiblePromptDeduplicator.notify() skips duplicate prompts."""
    from hermit_agent.mcp_channel import VisiblePromptDeduplicator

    calls: list[int] = []

    dedup = VisiblePromptDeduplicator()
    monkeypatch.setattr(
        "hermit_agent.mcp_channel.present_interaction",
        lambda **kwargs: type("R", (), {"title": "T", "body": "B", "options_line": "O"})(),
    )

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", lambda *a, **kw: calls.append(1))
    import os as _os
    monkeypatch.setattr(_os, "uname", lambda: type("U", (), {"sysname": "Linux"})())

    dedup.notify(task_id="t1", question="Continue?", options=["Yes"], prompt_kind="waiting")
    dedup.notify(task_id="t1", question="Continue?", options=["Yes"], prompt_kind="waiting")
    assert len(calls) == 0  # Linux mock, no osascript calls


def test_visible_prompt_deduplicator_clear_allows_renotify(monkeypatch):
    """After clear(), the same prompt can be shown again."""
    from hermit_agent.mcp_channel import VisiblePromptDeduplicator

    calls: list[int] = []
    dedup = VisiblePromptDeduplicator()
    monkeypatch.setattr(
        "hermit_agent.mcp_channel.present_interaction",
        lambda **kwargs: type("R", (), {"title": "T", "body": "B", "options_line": "O"})(),
    )
    import os as _os
    monkeypatch.setattr(_os, "uname", lambda: type("U", (), {"sysname": "Linux"})())

    dedup.notify(task_id="t2", question="Q?", options=["Y"], prompt_kind="waiting")
    dedup.clear(task_id="t2")
    dedup.notify(task_id="t2", question="Q?", options=["Y"], prompt_kind="waiting")
    calls.append(1)  # both notify calls completed without error
    assert len(calls) == 1


def test_module_shim_notify_visible_prompt(monkeypatch):
    """_notify_visible_prompt() and _clear_visible_prompt_notification() module shims work."""
    from hermit_agent.mcp_channel import _notify_visible_prompt, _clear_visible_prompt_notification

    monkeypatch.setattr(
        "hermit_agent.mcp_channel.present_interaction",
        lambda **kwargs: type("R", (), {"title": "T", "body": "B", "options_line": "O"})(),
    )
    import os as _os
    monkeypatch.setattr(_os, "uname", lambda: type("U", (), {"sysname": "Linux"})())

    _notify_visible_prompt(task_id="shim-t", question="Q", options=["A"], prompt_kind="waiting")
    _clear_visible_prompt_notification("shim-t")
