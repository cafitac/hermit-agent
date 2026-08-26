# Codex setup

```bash
npm install -g @cafitac/hermit-agent
# Configure Ollama first, or run `hermit configure` for an OpenAI-compatible executor.
hermit install codex
hermit doctor
```

This runs Codex's MCP registration command for `hermit` and configures
it to invoke:

```text
hermit mcp-server
```

`hermit doctor` must report a ready executor before the host delegates work.
Restart Codex after installation. The same user-level registration is shared by
the Codex CLI, desktop app, and IDE extension.
