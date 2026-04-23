"""MCP (Model Context Protocol) client — stdio transport.

Connects to external MCP servers to dynamically load tools.
Communicates via JSON-RPC 2.0 over stdin/stdout.

Configuration file: ~/.hermit/mcp.json or .hermit/mcp.json
Format:
  {
    "servers": {
      "my-server": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {"MY_VAR": "value"}
      }
    }
  }
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from .tools import Tool, ToolResult
from .version import VERSION

logger = logging.getLogger(__name__)

MCP_CONFIG_PATHS = [
    os.path.expanduser("~/.hermit/mcp.json"),
    ".hermit/mcp.json",
]

MCP_CONFIG_TEMPLATE = {
    "servers": {
        # Example: filesystem server (commented out by default)
        # "filesystem": {
        #   "command": "npx",
        #   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        #   "env": {}
        # }
    }
}


class MCPClient:
    """MCP client — stdio transport. Communicates with external MCP servers via JSON-RPC."""

    def __init__(self, name: str, command: str, args: list[str] = None, env: dict = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._tools: list[dict] = []

    def connect(self) -> None:
        """Starts the MCP server subprocess and performs the initialization handshake."""
        if self._process and self._process.poll() is None:
            return

        env = {**os.environ}
        if self.env:
            env.update(self.env)

        self._process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        # MCP initialize handshake
        init_result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "hermit_agent", "version": VERSION},
        })

        if "error" in init_result:
            raise RuntimeError(f"MCP init failed for '{self.name}': {init_result['error']}")

        # Send initialized notification (no response expected)
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._write_message(notification)

    def disconnect(self) -> None:
        """Terminates the MCP server process."""
        if self._process:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            finally:
                self._process = None

    def list_tools(self) -> list[dict]:
        """Sends a tools/list request and returns the list of tool definitions."""
        result = self._send_request("tools/list")
        if "error" in result:
            logger.warning("MCP '%s' tools/list error: %s", self.name, result["error"])
            return []
        tools = result.get("result", {}).get("tools", [])
        self._tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Sends a tools/call request and returns the result string."""
        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if "error" in result:
            raise RuntimeError(f"MCP tool call error: {result['error']}")

        call_result = result.get("result", {})

        # MCP result is in content array format
        content_items = call_result.get("content", [])
        if not content_items:
            return ""

        parts = []
        for item in content_items:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("type") == "image":
                parts.append(f"[image: {item.get('mimeType', 'unknown')}]")
            else:
                parts.append(str(item))

        return "\n".join(parts)

    def _send_request(self, method: str, params: dict = None) -> dict:
        """Sends a JSON-RPC request and returns the response."""
        if not self._process or self._process.poll() is not None:
            raise RuntimeError(f"MCP server '{self.name}' is not running")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        self._write_message(request)
        return self._read_response(self._request_id)

    def _write_message(self, message: dict) -> None:
        """Sends a JSON message to the server's stdin."""
        line = json.dumps(message) + "\n"
        try:
            self._process.stdin.write(line)
            self._process.stdin.flush()
        except BrokenPipeError as e:
            raise RuntimeError(f"MCP server '{self.name}' stdin pipe broken: {e}") from e

    def _read_response(self, expected_id: int, timeout: float = 30.0) -> dict:
        """Reads and returns the JSON-RPC response from the server's stdout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._process.stdout.readline()
            except Exception as e:
                raise RuntimeError(f"MCP server '{self.name}' read error: {e}") from e

            if not line:
                # If the process has terminated
                stderr = ""
                try:
                    stderr = self._process.stderr.read(500)
                except Exception:
                    pass
                raise RuntimeError(
                    f"MCP server '{self.name}' closed stdout unexpectedly. stderr: {stderr}"
                )

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Ignore non-JSON output (e.g., logs) from the server
                continue

            # Skip notification messages (no id)
            if "id" not in msg:
                continue

            if msg.get("id") == expected_id:
                return msg

        raise TimeoutError(
            f"MCP server '{self.name}' did not respond to request {expected_id} within {timeout}s"
        )

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def __repr__(self) -> str:
        status = "connected" if self.is_connected else "disconnected"
        return f"MCPClient(name={self.name!r}, command={self.command!r}, status={status})"


class MCPToolAdapter(Tool):
    """Adapting MCP server tools to HermitAgent's Tool interface."""

    DESCRIPTION_LIMIT = 2048
    RESULT_LIMIT = 30000

    def __init__(self, client: MCPClient, tool_def: dict):
        self._client = client
        self._tool_name = tool_def["name"]
        self.name = f"mcp_{client.name}_{self._tool_name}"
        self.description = tool_def.get("description", "")[:self.DESCRIPTION_LIMIT]
        self._schema = tool_def.get("inputSchema", {})

    def input_schema(self) -> dict:
        return self._schema

    def execute(self, input: dict) -> ToolResult:
        if not self._client.is_connected:
            return ToolResult(
                content=f"MCP server '{self._client.name}' is not connected",
                is_error=True,
            )
        try:
            result = self._client.call_tool(self._tool_name, input)
            return ToolResult(content=result[:self.RESULT_LIMIT])
        except Exception as e:
            return ToolResult(content=f"MCP tool error ({self.name}): {e}", is_error=True)

    @property
    def is_read_only(self) -> bool:
        return False

    @property
    def is_concurrent_safe(self) -> bool:
        return False


class MCPManager:
    """Load MCP configuration and manage server connections."""

    def __init__(self):
        self.clients: dict[str, MCPClient] = {}
        self._config: dict = {}
        self._load_config()

    def _load_config(self) -> None:
        """Loads ~/.hermit/mcp.json and .hermit/mcp.json.

        Local settings merge (override) global settings.
        """
        merged: dict = {"servers": {}}

        for config_path in MCP_CONFIG_PATHS:
            expanded = os.path.expanduser(config_path)
            if not os.path.exists(expanded):
                continue
            try:
                with open(expanded) as f:
                    data = json.load(f)
                servers = data.get("servers", {})
                merged["servers"].update(servers)
            except Exception as e:
                logger.warning("Failed to load MCP config %s: %s", expanded, e)

        self._config = merged

        for server_name, server_cfg in merged.get("servers", {}).items():
            command = server_cfg.get("command")
            if not command:
                logger.warning("MCP server '%s' has no 'command', skipping", server_name)
                continue
            self.clients[server_name] = MCPClient(
                name=server_name,
                command=command,
                args=server_cfg.get("args", []),
                env=server_cfg.get("env"),
            )

    def connect_all(self) -> list[Tool]:
        """Connects to all configured servers and returns the list of adapted tools."""
        tools: list[Tool] = []

        for name, client in self.clients.items():
            try:
                client.connect()
                tool_defs = client.list_tools()
                for tool_def in tool_defs:
                    tools.append(MCPToolAdapter(client, tool_def))
                logger.info(
                    "MCP '%s': connected, %d tools loaded", name, len(tool_defs)
                )
            except Exception as e:
                logger.warning("MCP '%s': failed to connect — %s", name, e)

        return tools

    def disconnect_all(self) -> None:
        """Terminates all server connections."""
        for client in self.clients.values():
            try:
                client.disconnect()
            except Exception as e:
                logger.warning("MCP '%s': error during disconnect — %s", client.name, e)

    def status(self) -> list[dict]:
        """Returns the status information of each server."""
        result = []
        for name, client in self.clients.items():
            result.append({
                "name": name,
                "command": f"{client.command} {' '.join(client.args)}".strip(),
                "connected": client.is_connected,
                "tools": len(client._tools),
            })
        return result


def ensure_default_config() -> None:
    """Creates a default template if ~/.hermit/mcp.json does not exist."""
    global_config = os.path.expanduser("~/.hermit/mcp.json")
    if os.path.exists(global_config):
        return

    os.makedirs(os.path.dirname(global_config), exist_ok=True)
    try:
        with open(global_config, "w") as f:
            json.dump(MCP_CONFIG_TEMPLATE, f, indent=2)
            f.write("\n")
        logger.info("Created default MCP config at %s", global_config)
    except Exception as e:
        logger.warning("Could not create default MCP config: %s", e)
