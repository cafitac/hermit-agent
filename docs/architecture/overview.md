# Architecture

Hermit keeps premium host-agent context for planning and review, while routing
bounded execution to a local or lower-cost model. This is the product boundary:
it reduces routine execution cost without asking users to abandon Claude Code
or Codex.

Hermit has one supported job: execute a repository task received over MCP.

```text
Claude Code, Codex, or Claude Desktop
        │ stdio MCP
        ▼
hermit mcp-server
        │ HTTP task API
        ▼
Gateway
        │ model routing + task state
        ▼
AgentLoop
        │ repository tools
        ▼
Working directory
```

## Public boundary

The `hermit` MCP server exposes four tools only:

1. `run_task` starts a background executor task.
2. `check_task` returns `running`, `waiting`, `done`, `needs_review`, or `error`.
3. `reply_task` supplies a required user or permission response.
4. `cancel_task` stops a task.

Hosts poll `check_task`; Hermit does not rely on host-specific channel
notifications, UI bridges, or a persistent chat protocol.

Claude Desktop receives the same stdio server through the release's UV-backed
MCPB bundle. The bundle installs the matching Hermit Python package with its
managed runtime, while Claude Code and Codex register `hermit mcp-server`
through their own CLIs.

## Runtime ownership

- The MCP process validates and forwards task-lifecycle requests.
- The gateway owns task state, cancellation, permissions, and model routing.
  Provider profiles can point at any OpenAI-compatible Chat Completions API.
- `AgentLoop` owns LLM/tool iteration and context compaction.
- Tools operate only in the task's requested working directory under the
  configured permission policy.
