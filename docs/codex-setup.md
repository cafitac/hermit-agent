# Codex setup

```bash
npm install -g @cafitac/hermit-agent
hermit install codex
```

This runs Codex's MCP registration command for `hermit` and configures
it to invoke:

```text
hermit mcp-server
```

Restart Codex after installation. The same user-level registration is shared
by the Codex CLI, desktop app, and IDE extension. Use `hermit doctor` to check
the MCP registration and the local gateway.
