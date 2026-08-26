# Hermit Project Configuration

Hermit is a small MCP coding executor for Claude Code and Codex.

```text
hermit_agent/  Python MCP, gateway, agent loop, and tools
bin/           npm launcher and development launchers
docs/          concise setup and architecture guides
tests/         regression tests
```

Keep the public CLI limited to install, doctor, and mcp-server. The product is
used through an MCP host, not through an independent conversational interface.

```bash
.venv/bin/python -m pytest tests/
```
