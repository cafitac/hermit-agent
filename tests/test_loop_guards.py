"""§29 Regression test for P0 bug fixes.

- Bug 1 (G26): Speculative edit infinite loop — block 3 consecutive edits on the same file + force read
- Bug 2 (G25): Excessive context compression — prohibit compact trigger below threshold * 0.8
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.context import ContextManager
from hermit_agent.llm_client import OllamaClient, LLMResponse
from hermit_agent.loop import AgentLoop
from hermit_agent.permissions import PermissionMode
from hermit_agent.tools import create_default_tools


class _StubLLM(OllamaClient):
    def __init__(self):
        self.model = "stub"

    def chat(self, messages, system=None, tools=None, abort_event=None):
        return LLMResponse(content="ok", tool_calls=[])

    def chat_stream(self, messages, system=None, tools=None, abort_event=None):
        yield from []


def _make_agent(cwd: str) -> AgentLoop:
    tools = create_default_tools(cwd=cwd)
    return AgentLoop(
        llm=_StubLLM(),
        tools=tools,
        cwd=cwd,
        permission_mode=PermissionMode.YOLO,
    )


# ─── Bug 2: Excessive context compression ────────────────────────────


def test_compact_threshold_is_95_percent_of_context_window():
    """Threshold = context_window * 0.95 (dynamic adjustment)."""
    cm = ContextManager(max_context_tokens=32000)
    assert cm.threshold == 30400


def test_compact_not_triggered_below_80_percent_of_threshold():
    """If the actual token count is below threshold * 0.8, compact triggering is prohibited.

    threshold=24000 → 0.8 * 24000 = 19200. A 19000-token message is not compacted.
    """
    cm = ContextManager(max_context_tokens=32000)
    # Message equivalent to 19000 tokens (estimate_tokens is len(text) // 3, so 57000 characters ≈ 19000 tokens)
    content = "a" * (19000 * 3)
    messages = [{"role": "user", "content": content}]
    assert cm.get_compact_level(messages) == 0
    assert not cm.should_compact(messages)


def test_compact_triggered_above_80_percent_of_threshold():
    """Compact triggers if compact_start_ratio(0.85) * threshold(30400) = 25840 or higher."""
    cm = ContextManager(max_context_tokens=32000)
    # 26000 tokens worth (exceeds 25840)
    content = "a" * (26000 * 3)
    messages = [{"role": "user", "content": content}]
    assert cm.get_compact_level(messages) >= 1


# ─── Bug 1: Block 3 consecutive edits to the same file ────────────────


def test_third_consecutive_edit_same_file_is_blocked():
    """If the same file is edited 3 consecutive times without a read, the 3rd edit is blocked."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "target.py")
        with open(path, "w") as f:
            f.write("line_a\nline_b\nline_c\n")

        agent = _make_agent(tmp)

        # EditFileTool prerequisite: initial read_file (registered in global read_files set)
        agent._execute_tool("read_file", {"path": path})
        # Loop guard state initialization: since the test verifies "consecutive edits after read"
        # Remove the effect of the just-performed read (guard catches repetitions "without read after edit").
        agent._guards._read_paths_since_last_edit.clear()

        # 1st edit
        r1 = agent._execute_tool(
            "edit_file",
            {"path": path, "old_string": "line_a", "new_string": "line_A"},
        )
        assert not r1.is_error, r1.content

        # 2nd edit (without intermediate read_file)
        r2 = agent._execute_tool(
            "edit_file",
            {"path": path, "old_string": "line_b", "new_string": "line_B"},
        )
        assert not r2.is_error, r2.content

        # G48: Loop guard triggers only on speculative edits after test failure
        # (Planned edits of multiple sections without test failure should be allowed)
        agent._guards.consecutive_test_failures = 1

        # 3rd edit — should be blocked by loop guard
        r3 = agent._execute_tool(
            "edit_file",
            {"path": path, "old_string": "line_c", "new_string": "line_C"},
        )
        assert r3.is_error
        assert "Loop guard" in r3.content
        assert "read_file" in r3.content


def test_read_file_resets_edit_streak():
    """Calling read_file in between resets the streak, so the 3rd edit is also allowed."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "target.py")
        with open(path, "w") as f:
            f.write("line_a\nline_b\nline_c\n")

        agent = _make_agent(tmp)

        # EditFileTool preconditions met
        agent._execute_tool("read_file", {"path": path})
        agent._guards._read_paths_since_last_edit.clear()

        r1 = agent._execute_tool("edit_file", {"path": path, "old_string": "line_a", "new_string": "line_A"})
        assert not r1.is_error
        r2 = agent._execute_tool("edit_file", {"path": path, "old_string": "line_b", "new_string": "line_B"})
        assert not r2.is_error

        # read_file call → streak reset
        rr = agent._execute_tool("read_file", {"path": path})
        assert not rr.is_error

        # 3rd edit — should now be allowed
        r3 = agent._execute_tool("edit_file", {"path": path, "old_string": "line_c", "new_string": "line_C"})
        assert not r3.is_error, r3.content


def test_different_file_edit_does_not_trigger_guard():
    """Alternating edits to different files does not build up a streak for the same file."""
    with tempfile.TemporaryDirectory() as tmp:
        path_a = os.path.join(tmp, "a.py")
        path_b = os.path.join(tmp, "b.py")
        for p in (path_a, path_b):
            with open(p, "w") as f:
                f.write("xxx\nyyy\nzzz\n")

        agent = _make_agent(tmp)

        for p in (path_a, path_b, path_a, path_b, path_a):
            r = agent._execute_tool("edit_file", {"path": p, "old_string": "xxx", "new_string": "XXX"})
            # Do not check is_error since it may fail due to missing old_string after the first success.
            # However, it should not be blocked by the "Loop guard".
            assert "Loop guard" not in r.content


# ─── Bug 1: read_file hint upon consecutive test failures ────────────


def test_consecutive_test_failures_trigger_read_hint():
    """If run_tests fails 2 consecutive times, a system-reminder is injected right before the next LLM call."""
    from hermit_agent.tools import ToolResult

    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)

        # Simulate 2 run_tests failures — call track_loop_state directly
        agent._track_loop_state("run_tests", {}, ToolResult(content="FAIL", is_error=True))
        agent._track_loop_state("run_tests", {}, ToolResult(content="FAIL", is_error=True))

        assert agent._guards.consecutive_test_failures >= 2

        # Call hint injection method
        before = len(agent.messages)
        agent._maybe_inject_test_failure_hint()
        assert len(agent.messages) == before + 1
        injected = agent.messages[-1]
        assert injected["role"] == "user"
        assert "read_file" in injected["content"]
        assert "system-reminder" in injected["content"]

        # Once injected, prevent duplicate injection for the same failure count
        agent._maybe_inject_test_failure_hint()
        assert len(agent.messages) == before + 1


def test_successful_test_resets_failure_counter():
    from hermit_agent.tools import ToolResult

    with tempfile.TemporaryDirectory() as tmp:
        agent = _make_agent(tmp)
        agent._track_loop_state("run_tests", {}, ToolResult(content="FAIL", is_error=True))
        agent._track_loop_state("run_tests", {}, ToolResult(content="PASS", is_error=False))
        assert agent._guards.consecutive_test_failures == 0


# ─── LoopGuards unit tests ────────────────────────────────────────────────────


def _make_guards(tmp_path_str: str):
    from hermit_agent.loop_guards import LoopGuards
    return LoopGuards(cwd=tmp_path_str)


def _tool_result(*, is_error: bool = False, content: str = "ok"):
    from hermit_agent.tools import ToolResult
    return ToolResult(content=content, is_error=is_error)


def test_loop_guards_check_edit_loop_ignores_non_edit():
    with tempfile.TemporaryDirectory() as tmp:
        guards = _make_guards(tmp)
        assert guards.check_edit_loop("bash", {"command": "ls"}) is None
        assert guards.check_edit_loop("read_file", {"path": "foo.py"}) is None


def test_loop_guards_blocks_third_edit_after_test_failure():
    with tempfile.TemporaryDirectory() as tmp:
        guards = _make_guards(tmp)
        path = os.path.join(tmp, "foo.py")
        guards.track("run_tests", {}, _tool_result(is_error=True))
        guards.track("edit_file", {"path": path}, _tool_result())
        guards.track("edit_file", {"path": path}, _tool_result())
        result = guards.check_edit_loop("edit_file", {"path": path})
        assert result is not None and result.is_error and "Loop guard" in result.content


def test_loop_guards_no_block_without_test_failure():
    with tempfile.TemporaryDirectory() as tmp:
        guards = _make_guards(tmp)
        path = os.path.join(tmp, "foo.py")
        guards.track("edit_file", {"path": path}, _tool_result())
        guards.track("edit_file", {"path": path}, _tool_result())
        assert guards.check_edit_loop("edit_file", {"path": path}) is None


def test_loop_guards_track_test_pass_resets_failures():
    with tempfile.TemporaryDirectory() as tmp:
        guards = _make_guards(tmp)
        guards.track("run_tests", {}, _tool_result(is_error=True))
        guards.track("run_tests", {}, _tool_result(is_error=True))
        assert guards.consecutive_test_failures == 2
        guards.track("run_tests", {}, _tool_result(is_error=False))
        assert guards.consecutive_test_failures == 0
        assert guards.total_test_passes == 1
