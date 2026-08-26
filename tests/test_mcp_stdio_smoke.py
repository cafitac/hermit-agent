"""Release smoke coverage for the public stdio MCP entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]


async def _list_public_tools(home: Path) -> list[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            # The stdio protocol itself must work without mutating host state
            # or starting a background gateway process.
            "HERMIT_MCP_AUTO_GATEWAY": "0",
            "HERMIT_LOG_PATH": os.devnull,
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hermit_agent", "mcp-server"],
        cwd=REPO_ROOT,
        env=environment,
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()

    assert initialized.serverInfo.name == "hermit"
    return [tool.name for tool in tools.tools]


def test_mcp_stdio_entry_point_handshakes_from_a_clean_home(tmp_path: Path) -> None:
    tool_names = anyio.run(_list_public_tools, tmp_path)

    assert tool_names == ["run_task", "reply_task", "check_task", "cancel_task"]
    assert not (tmp_path / ".hermit").exists()
