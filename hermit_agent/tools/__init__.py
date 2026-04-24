"""Tool implementations. See `hermit_agent.tool_base` for the Tool interface.

Refactoring in progress (`docs/refactor-plan.md` Phase A done, B pending). External import
paths (`from hermit_agent.tools import Tool`, etc.) remain stable — this file is the re-export point.
"""

from __future__ import annotations

from .base import (
    Tool,
    ToolResult,
    _check_secrets,
    _display_path,
    _expand_path,
    _format_content_preview,
    _is_safe_path,
    _redirect_to_worktree_path,
)
from .fs import (
    EditFileTool,
    NotebookEditTool,
    ReadFileTool,
    WriteFileTool,
    _format_edit_diff,
    _shorten_path,
)
from .agent import SubAgentTool
from .interaction import AskUserQuestionTool
from .memory import MemoryReadTool, MemoryWriteTool
from .search import GlobTool, GrepTool
from .shell import BashTool, MonitorTool
from .skill import RunSkillTool, ToolSearchTool, _normalize_phase_key
from .state import StateReadTool, StateWriteTool
from .testing import RunTestsTool

__all__ = [
    "Tool",
    "ToolResult",
    "_check_secrets",
    "_display_path",
    "_expand_path",
    "_format_content_preview",
    "_is_safe_path",
    "_redirect_to_worktree_path",
    "EditFileTool",
    "NotebookEditTool",
    "ReadFileTool",
    "WriteFileTool",
    "_format_edit_diff",
    "_shorten_path",
    "SubAgentTool",
    "AskUserQuestionTool",
    "MemoryReadTool",
    "MemoryWriteTool",
    "GlobTool",
    "GrepTool",
    "BashTool",
    "MonitorTool",
    "RunSkillTool",
    "ToolSearchTool",
    "_normalize_phase_key",
    "StateReadTool",
    "StateWriteTool",
    "RunTestsTool",
    "create_default_tools",
]


def create_default_tools(cwd: str = ".", llm_client=None, question_queue=None, reply_queue=None, notify_fn=None, notify_running_fn=None) -> list[Tool]:
    """Create the default tool set.

    question_queue / reply_queue: inject queues so that ask_user_question waits
    for an actual answer in MCP bidirectional mode.
    notify_fn: callback to push a waiting state to hermit-channel (optional).
    notify_running_fn: running notification callback to exit retry loop after consuming a reply (optional).
    """
    from .web import DeepSearchTool, GitHubSearchTool, StackOverflowSearchTool, WebFetchTool, WebSearchTool

    read_tool = ReadFileTool(cwd=cwd)
    web_search = WebSearchTool()
    web_fetch = WebFetchTool()
    tools: list[Tool] = [
        BashTool(cwd=cwd),
        MonitorTool(),
        RunTestsTool(cwd=cwd),
        RunSkillTool(),
        AskUserQuestionTool(question_queue=question_queue, reply_queue=reply_queue, notify_fn=notify_fn, notify_running_fn=notify_running_fn),
        StateWriteTool(cwd=cwd),
        StateReadTool(cwd=cwd),
        read_tool,
        WriteFileTool(cwd=cwd),
        EditFileTool(read_file_tool=read_tool, cwd=cwd),
        NotebookEditTool(),
        GlobTool(cwd=cwd),
        GrepTool(cwd=cwd),
        MemoryReadTool(),
        MemoryWriteTool(),
        web_search,
        web_fetch,
        DeepSearchTool(web_search=web_search, web_fetch=web_fetch),
        StackOverflowSearchTool(),
        GitHubSearchTool(),
    ]

    if llm_client:
        tools.append(SubAgentTool(
            llm_client=llm_client,
            tools_factory=lambda c: create_default_tools(cwd=c),  # prevent recursion: sub-agent does not get sub_agent tool
            cwd=cwd,
        ))

        from ..coordinator import CoordinatorTool
        tools.append(CoordinatorTool(llm=llm_client, cwd=cwd))

    # Load MCP tools (optional — silently skipped if not configured)
    try:
        from ..mcp import MCPManager, ensure_default_config
        ensure_default_config()
        mcp = MCPManager()
        tools.extend(mcp.connect_all())
    except Exception:
        pass

    return tools
