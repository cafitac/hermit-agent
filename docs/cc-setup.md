# Claude Code setup

```bash
npm install -g @cafitac/hermit-agent
hermit install claude
```

This uses Claude Code's user-scoped MCP command to register `hermit`
for every local project as:

```text
hermit mcp-server
```

Restart Claude Code, then delegate a scoped coding task with the
Hermit's MCP tools. Run `hermit doctor` if the server does not appear.
