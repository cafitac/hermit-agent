"""Smoke test for import paths + default execution paths of all Tool classes.

Phase E post-mortem recurrence prevention: immediately detect missing/circular imports after refactoring.
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_all_tool_classes_importable():
    """Verify that all public symbols are importable from hermit_agent.tools."""
    from hermit_agent.tools import (
        AskUserQuestionTool,
        BashTool,
        EditFileTool,
        GlobTool,
        GrepTool,
        MemoryReadTool,
        MemoryWriteTool,
        NotebookEditTool,
        ReadFileTool,
        RunSkillTool,
        RunTestsTool,
        StateReadTool,
        StateWriteTool,
        SubAgentTool,
        Tool,
        ToolSearchTool,
        ToolResult,
        WriteFileTool,
        create_default_tools,
    )
    # Successful import itself is verified — additionally checks types
    imported = (
        Tool,
        ToolResult,
        BashTool,
        ReadFileTool,
        WriteFileTool,
        EditFileTool,
        NotebookEditTool,
        GlobTool,
        GrepTool,
        RunTestsTool,
        MemoryReadTool,
        MemoryWriteTool,
        SubAgentTool,
        ToolSearchTool,
        RunSkillTool,
        AskUserQuestionTool,
        StateReadTool,
        StateWriteTool,
    )
    assert all(obj is not None for obj in imported)
    assert callable(create_default_tools)


def test_create_default_tools_returns_20_tools():
    """Calling `create_default_tools('.')` returns 20 Tools."""
    from hermit_agent.tools import create_default_tools, Tool

    tools = create_default_tools(".")
    assert len(tools) == 20, f"expected 20 tools, got {len(tools)}: {[t.name for t in tools]}"
    for t in tools:
        assert isinstance(t, Tool), f"{t!r} is not a Tool instance"


def test_all_tools_have_openai_schema():
    """Calling each Tool's `to_openai_schema()` → no errors + function.name exists."""
    from hermit_agent.tools import create_default_tools

    tools = create_default_tools(".")
    for tool in tools:
        schema = tool.to_openai_schema()
        assert "function" in schema, f"{tool.name}: schema missing 'function' key"
        assert "name" in schema["function"], f"{tool.name}: schema['function'] missing 'name'"
        assert schema["function"]["name"], f"{tool.name}: schema function name is empty"


def test_glob_tool_basic_execution():
    """GlobTool(cwd=tmp) + execute({"pattern": "*.txt"}) → returns ToolResult (verifies import/runtime)."""
    from hermit_agent.tools import GlobTool, ToolResult

    with tempfile.TemporaryDirectory() as tmp:
        # Create one txt file
        open(os.path.join(tmp, "hello.txt"), "w").close()

        tool = GlobTool(cwd=tmp)
        result = tool.execute({"pattern": "*.txt"})

        assert isinstance(result, ToolResult), f"expected ToolResult, got {type(result)}"


def test_ask_user_question_tool_accepts_notify_fn():
    """AskUserQuestionTool must accept the notify_fn parameter (prevents TypeError recurrence)."""
    from hermit_agent.tools import AskUserQuestionTool

    q_in = queue.Queue()
    q_out = queue.Queue()
    called = []

    def fake_notify(question, options):
        called.append((question, options))

    # Must be created without TypeError
    tool = AskUserQuestionTool(
        question_queue=q_in,
        reply_queue=q_out,
        notify_fn=fake_notify,
    )
    assert tool is not None


def test_ask_user_question_tool_calls_notify_fn_on_execute():
    """In MCP mode, notify_fn must be called upon execute."""
    from hermit_agent.tools import AskUserQuestionTool

    q_in = queue.Queue()
    q_out = queue.Queue()
    notified = []

    def fake_notify(question, options):
        notified.append(question)

    tool = AskUserQuestionTool(
        question_queue=q_in,
        reply_queue=q_out,
        notify_fn=fake_notify,
    )

    # execute blocks on reply_queue.get(), so inject response via thread
    def reply_thread():
        q_in.get()  # Consume question
        q_out.put("Test answer")

    t = threading.Thread(target=reply_thread, daemon=True)
    t.start()

    result = tool.execute({"question": "Continue?", "options": ["Yes", "No"]})
    t.join(timeout=2)

    assert "Test answer" in result.content
    assert len(notified) == 1
    assert "Continue?" in notified[0]


def test_ask_user_question_tool_errors_if_reply_queue_missing_in_bidirectional_mode():
    from hermit_agent.tools import AskUserQuestionTool

    q_out = queue.Queue()
    tool = AskUserQuestionTool(question_queue=q_out, reply_queue=None)

    result = tool.execute({"question": "Continue?", "options": ["Yes", "No"]})

    assert result.is_error
    assert "reply queue missing" in result.content


def test_create_default_tools_with_queues_and_notify_fn():
    """No TypeError when passing question_queue/reply_queue/notify_fn to create_default_tools."""
    from hermit_agent.tools import create_default_tools

    q_in = queue.Queue()
    q_out = queue.Queue()

    def fake_notify(question, options):
        pass

    # Must be created without TypeError
    tools = create_default_tools(
        cwd=".",
        question_queue=q_in,
        reply_queue=q_out,
        notify_fn=fake_notify,
    )
    assert len(tools) >= 20


def test_read_file_tool_basic_execution():
    """ReadFileTool().execute({"path": tmp_file}) → content includes file contents."""
    from hermit_agent.tools import ReadFileTool, ToolResult

    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "sample.txt")
        with open(target, "w") as f:
            f.write("hello hermit_agent")

        tool = ReadFileTool()
        result = tool.execute({"path": target})

        assert isinstance(result, ToolResult), f"expected ToolResult, got {type(result)}"
        assert "hello hermit_agent" in result.content, (
            f"file content not found in result: {result.content!r}"
        )
