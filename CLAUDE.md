# Hermit Project — MCP Executor

Hermit is a minimal MCP coding executor for Claude Code and Codex. Python
3.11+, FastAPI.

## Key modules

- `hermit_agent/mcp_server.py` — the four public MCP task tools
- `hermit_agent/gateway/` — background task lifecycle and model routing
- `hermit_agent/loop.py` — LLM/tool execution loop
- `hermit_agent/tools/` — repository operations under the permission policy

## Public CLI

```bash
hermit install claude
hermit install codex
hermit mcp-server
hermit doctor
```

## Tests

```bash
.venv/bin/python -m pytest tests/
```

## Product boundary

Hermit is an MCP executor, not a standalone chat UI. Do not add a terminal UI,
host-specific interactive protocol, or unrelated orchestration product without
an explicit product decision.
