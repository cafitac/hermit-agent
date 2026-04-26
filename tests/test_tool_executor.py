"""US-003: Unit tests for ToolExecutor class."""
from __future__ import annotations

import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_executor(tmp_path: str):
    from hermit_agent.tool_executor import ToolExecutor
    from hermit_agent.loop import AgentLoop
    from hermit_agent.permissions import PermissionMode
    from hermit_agent.tools import create_default_tools
    from hermit_agent.llm_client import OllamaClient, LLMResponse

    class _StubLLM(OllamaClient):
        def __init__(self):
            self.model = "stub"
        def chat(self, messages, system=None, tools=None, abort_event=None):
            return LLMResponse(content="ok", tool_calls=[])
        def chat_stream(self, messages, system=None, tools=None, abort_event=None):
            yield from []

    tools = create_default_tools(cwd=tmp_path)
    agent = AgentLoop(llm=_StubLLM(), tools=tools, cwd=tmp_path, permission_mode=PermissionMode.YOLO)
    return ToolExecutor(agent=agent), agent


def test_tool_executor_unknown_tool_returns_error():
    with tempfile.TemporaryDirectory() as tmp:
        executor, _ = _make_executor(tmp)
        result = executor.execute_tool("nonexistent_tool_xyz", {})
        assert result.is_error
        assert "Unknown tool" in result.content


def test_tool_executor_executes_known_tool():
    with tempfile.TemporaryDirectory() as tmp:
        import os
        test_file = os.path.join(tmp, "hello.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        executor, _ = _make_executor(tmp)
        result = executor.execute_tool("read_file", {"path": test_file})
        assert not result.is_error
        assert "hello" in result.content


def test_tool_executor_same_as_agent_execute_tool():
    """ToolExecutor.execute_tool and AgentLoop._execute_tool use the same logic."""
    with tempfile.TemporaryDirectory() as tmp:
        import os
        # Use separate agents to avoid shared state between two reads
        executor1, _ = _make_executor(tmp)
        executor2, _ = _make_executor(tmp)
        test_file = os.path.join(tmp, "test.txt")
        with open(test_file, "w") as f:
            f.write("content")

        r1 = executor1.execute_tool("read_file", {"path": test_file})
        r2 = executor2._agent._execute_tool("read_file", {"path": test_file})
        assert r1.is_error == r2.is_error
        assert "content" in r1.content
        assert "content" in r2.content


def test_partition_tool_calls_groups_safe_tools():
    """partition_tool_calls groups concurrent-safe tools into parallel batches."""
    with tempfile.TemporaryDirectory() as tmp:
        executor, agent = _make_executor(tmp)
        from types import SimpleNamespace

        # read_file is concurrent-safe, bash is not
        read_tc = SimpleNamespace(id="r1", name="read_file", arguments={"path": "a.txt"})
        read_tc2 = SimpleNamespace(id="r2", name="read_file", arguments={"path": "b.txt"})
        bash_tc = SimpleNamespace(id="b1", name="bash", arguments={"command": "ls"})

        batches = executor.partition_tool_calls([read_tc, read_tc2, bash_tc])
        assert len(batches) == 2
        first_batch, first_is_parallel = batches[0]
        assert first_is_parallel is True
        assert len(first_batch) == 2
        second_batch, second_is_parallel = batches[1]
        assert second_is_parallel is False
        assert len(second_batch) == 1
