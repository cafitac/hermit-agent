# Claude Code setup

```bash
npm install -g @cafitac/hermit-agent
# Configure Ollama first, or run `hermit configure` for an OpenAI-compatible executor.
hermit install claude
hermit doctor
```

This uses Claude Code's user-scoped MCP command to register `hermit`
for every local project as:

```text
hermit mcp-server
```

`hermit doctor` must report a ready executor before the host delegates work.
Restart Claude Code, then delegate a scoped coding task with Hermit's MCP tools.
