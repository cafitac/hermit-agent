# Changelog

## v0.4.0

### Breaking changes

- Removed the standalone React/Ink terminal UI and its private interactive
  session/bridge runtime.
- Removed host-specific notification channels from the MCP runtime. Hosts use
  `check_task` polling and `reply_task` for every task state transition.
- Replaced the large standalone-agent CLI with `hermit install`,
  `hermit doctor`, and `hermit mcp-server`.
- Reduced the CLI surface to MCP installation and runtime commands.

### Installation

- `hermit install claude` registers `hermit` in Claude Code.
- `hermit install codex` registers `hermit` through the Codex CLI.
- `hermit install` registers both hosts.
- The matching GitHub Release includes a Claude Desktop `.mcpb` extension for
  macOS and Windows. It uses the UV runtime instead of a user-installed Python.

The stable configured command remains `hermit mcp-server`.
