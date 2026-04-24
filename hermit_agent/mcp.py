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
from dataclasses import dataclass
from typing import Any, IO

from .tools import Tool, ToolResult
from .version import VERSION

logger = logging.getLogger(__name__)

MCP_CONFIG_PATHS = [
    os.path.expanduser("~/.hermit/mcp.json"),
    ".hermit/mcp.json",
]

MCP_CONFIG_TEMPLATE: dict[str, dict[str, dict[str, object]]] = {
    "servers": {
        # Example: filesystem server (commented out by default)
        # "filesystem": {
        #   "command": "npx",
        #   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        #   "env": {}
        # }
    }
}


@dataclass
class _ProcessState:
    proc: subprocess.Popen[str]
    stdin: IO[str]
    stdout: IO[str]
    stderr: IO[str]


class MCPClient:
    """MCP client — stdio transport."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env) if env is not None else None
        self._process: _ProcessState | None = None
        self._request_id = 0
        self._tools: list[dict[str, Any]] = []

    def connect(self) -> None:
        """Starts the MCP server subprocess and performs the initialization handshake."""
        if self.is_connected:
            return

        env = dict(os.environ)
        if self.env is not None:
            env.update(self.env)

        proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            proc.kill()
            raise RuntimeError(f"MCP server '{self.name}' failed to expose stdio pipes")

        self._process = _ProcessState(
            proc=proc,
            stdin=proc.stdin,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

        init_result = self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "hermit_agent", "version": VERSION},
            },
        )
        if "error" in init_result:
            raise RuntimeError(f"MCP init failed for '{self.name}': {init_result['error']}")

        self._write_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def disconnect(self) -> None:
        """Terminates the MCP server process."""
        process = self._process
        if process is None:
            return
        try:
            process.stdin.close()
            process.proc.wait(timeout=5)
        except Exception:
            process.proc.kill()
        finally:
            self._process = None

    def list_tools(self) -> list[dict[str, Any]]:
        """Sends a tools/list request and returns the list of tool definitions."""
        result = self._send_request("tools/list")
        if "error" in result:
            logger.warning("MCP '%s' tools/list error: %s", self.name, result["error"])
            return []

        result_payload = result.get("result", {})
        if not isinstance(result_payload, dict):
            return []

        tools = result_payload.get("tools", [])
        if not isinstance(tools, list):
            return []

        normalized = [tool for tool in tools if isinstance(tool, dict)]
        self._tools = normalized
        return normalized

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Sends a tools/call request and returns the result string."""
        result = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )

        if "error" in result:
            raise RuntimeError(f"MCP tool call error: {result['error']}")

        call_result = result.get("result", {})
        if not isinstance(call_result, dict):
            return ""

        content_items = call_result.get("content", [])
        if not isinstance(content_items, list) or not content_items:
            return ""

        parts: list[str] = []
        for item in content_items:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type == "text":
                    parts.append(str(item.get("text", "")))
                elif item_type == "image":
                    parts.append(f"[image: {item.get('mimeType', 'unknown')}]")
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)

    def _send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Sends a JSON-RPC request and returns the response."""
        process = self._require_process()
        if process.proc.poll() is not None:
            raise RuntimeError(f"MCP server '{self.name}' is not running")

        self._request_id += 1
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        self._write_message(request)
        return self._read_response(self._request_id)

    def _write_message(self, message: dict[str, Any]) -> None:
        """Sends a JSON message to the server's stdin."""
        process = self._require_process()
        line = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            process.stdin.write(line)
            process.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError(f"MCP server '{self.name}' stdin pipe broken: {exc}") from exc

    def _read_response(self, expected_id: int, timeout: float = 30.0) -> dict[str, Any]:
        """Reads and returns the JSON-RPC response from the server's stdout."""
        deadline = time.monotonic() + timeout
        process = self._require_process()

        while time.monotonic() < deadline:
            try:
                line = process.stdout.readline()
            except Exception as exc:
                raise RuntimeError(f"MCP server '{self.name}' read error: {exc}") from exc

            if not line:
                stderr = ""
                if process.proc.poll() is not None:
                    try:
                        stderr = process.stderr.read().strip()
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"MCP server '{self.name}' terminated unexpectedly"
                        + (f": {stderr}" if stderr else "")
                    )
                time.sleep(0.01)
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("MCP '%s': ignoring invalid JSON line: %r", self.name, line)
                continue

            if not isinstance(msg, dict):
                continue

            if "id" not in msg:
                continue

            if msg["id"] != expected_id:
                logger.debug(
                    "MCP '%s': skipping out-of-order response id=%r (expected %r)",
                    self.name,
                    msg.get("id"),
                    expected_id,
                )
                continue

            return msg

        raise TimeoutError(f"MCP server '{self.name}' request timed out after {timeout}s")

    def _require_process(self) -> _ProcessState:
        if self._process is None:
            raise RuntimeError(f"MCP server '{self.name}' is not running")
        return self._process

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.proc.poll() is None

    def __repr__(self) -> str:
        status = "connected" if self.is_connected else "disconnected"
        return f"MCPClient(name={self.name!r}, command={self.command!r}, status={status})"


class MCPToolAdapter(Tool):
    """Adapt an MCP tool definition to HermitAgent's Tool interface."""

    DESCRIPTION_LIMIT = 2048
    RESULT_LIMIT = 30000

    def __init__(self, client: MCPClient, tool_def: dict[str, Any]):
        self._client = client
        self._tool_name = str(tool_def["name"])
        self.name = f"mcp_{client.name}_{self._tool_name}"
        self.description = str(tool_def.get("description", ""))[:self.DESCRIPTION_LIMIT]
        schema = tool_def.get("inputSchema", {})
        self._schema = schema if isinstance(schema, dict) else {}

    def input_schema(self) -> dict[str, Any]:
        return self._schema

    def execute(self, input: dict[str, Any]) -> ToolResult:
        if not self._client.is_connected:
            return ToolResult(
                content=f"MCP server '{self._client.name}' is not connected",
                is_error=True,
            )
        try:
            result = self._client.call_tool(self._tool_name, input)
            return ToolResult(content=result[:self.RESULT_LIMIT])
        except Exception as exc:
            return ToolResult(content=f"MCP tool error ({self.name}): {exc}", is_error=True)

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
        self._config: dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Loads ~/.hermit/mcp.json and .hermit/mcp.json.

        Local settings merge (override) global settings.
        """
        merged: dict[str, Any] = {"servers": {}}

        for config_path in MCP_CONFIG_PATHS:
            expanded = os.path.expanduser(config_path)
            if not os.path.exists(expanded):
                continue
            try:
                with open(expanded, encoding="utf-8") as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    continue
                servers = data.get("servers", {})
                if isinstance(servers, dict):
                    merged["servers"].update(servers)
            except Exception as exc:
                logger.warning("Failed to load MCP config %s: %s", expanded, exc)

        self._config = merged

        for server_name, server_cfg in merged.get("servers", {}).items():
            if not isinstance(server_name, str) or not isinstance(server_cfg, dict):
                continue
            command = server_cfg.get("command")
            if not command:
                logger.warning("MCP server '%s' has no 'command', skipping", server_name)
                continue
            args = server_cfg.get("args", [])
            env = server_cfg.get("env")
            self.clients[server_name] = MCPClient(
                name=server_name,
                command=str(command),
                args=[str(arg) for arg in args] if isinstance(args, list) else [],
                env={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else None,
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
                logger.info("MCP '%s': connected, %d tools loaded", name, len(tool_defs))
            except Exception as exc:
                logger.warning("MCP '%s': failed to connect — %s", name, exc)

        return tools

    def disconnect_all(self) -> None:
        """Terminates all server connections."""
        for client in self.clients.values():
            try:
                client.disconnect()
            except Exception as exc:
                logger.warning("MCP '%s': error during disconnect — %s", client.name, exc)

    def status(self) -> list[dict[str, Any]]:
        """Returns the status information of each server."""
        result: list[dict[str, Any]] = []
        for name, client in self.clients.items():
            result.append(
                {
                    "name": name,
                    "command": f"{client.command} {' '.join(client.args)}".strip(),
                    "connected": client.is_connected,
                    "tools": len(client._tools),
                }
            )
        return result


def ensure_default_config() -> None:
    """Creates a default template if ~/.hermit/mcp.json does not exist."""
    global_config = os.path.expanduser("~/.hermit/mcp.json")
    if os.path.exists(global_config):
        return

    os.makedirs(os.path.dirname(global_config), exist_ok=True)
    try:
        with open(global_config, "w", encoding="utf-8") as handle:
            json.dump(MCP_CONFIG_TEMPLATE, handle, indent=2)
            handle.write("\n")
        logger.info("Created default MCP config at %s", global_config)
    except Exception as exc:
        logger.warning("Could not create default MCP config: %s", exc)
