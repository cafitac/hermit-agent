# Hermit

**Spend premium agent tokens on judgment, not on routine execution.**

Hermit is a cost-optimized MCP coding executor for Claude Code, Codex, and
Claude Desktop. Your paid host agent plans, reviews, and makes the important
calls; Hermit delegates bounded repository work—reading and editing files,
running commands, and tests—to a local or lower-cost executor model.

It is a cost-optimization layer for agentic coding, not another chat UI and not
a replacement for Claude Code or Codex.

```text
Claude Code or Codex: plan, review, decide
                 │ delegate a bounded task
                 ▼
Hermit: execute with a local or lower-cost model
                 │ return status and result
                 ▼
Claude Code or Codex: verify and continue
```

## Install and run your first task

Requires Node.js 20+ and Python 3.11+.

Hermit deliberately does not use the Claude or Codex subscription as its
executor. Before delegating work, configure either a local Ollama model or one
OpenAI-compatible endpoint. `hermit doctor` verifies this explicitly, so a
host registration alone is never presented as a working executor.

### 1. Install Hermit

```bash
npm install -g @cafitac/hermit-agent
```

### 2. Choose an executor

For a local, no-per-token-cost executor:

```bash
ollama pull qwen3-coder:30b
```

For any OpenAI-compatible Chat Completions API, keep the secret in your shell
or operating-system secret store and register only its environment-variable
name:

```bash
export BUDGET_PROVIDER_API_KEY="…"
hermit configure \
  --model coder-small \
  --base-url https://llm.example.com/v1 \
  --api-key-env BUDGET_PROVIDER_API_KEY
```

`hermit configure` never accepts or writes an API key. It stores the endpoint,
model, and environment-variable reference in `~/.hermit/settings.json`.

### 3. Register the host

#### Claude Code

```bash
hermit install claude
```

#### Codex

```bash
hermit install codex
```

`hermit install claude` registers only Claude Code, and `hermit install codex`
registers only Codex. Bare `hermit install` registers both hosts. Each command
creates local Hermit settings if needed, starts or recovers the local gateway,
and registers this stable stdio command with the selected host:

```text
hermit mcp-server
```

The gateway binds to loopback only. If another process owns its default port,
Hermit leaves that process untouched and selects a free local port for its own
gateway.

### 4. Verify readiness

```bash
hermit doctor
```

Only delegate work after it reports a ready executor. Restart the selected host
after installation. `hermit install codex` writes the shared Codex MCP
configuration, so the same registration is available to the Codex CLI, desktop
app, and IDE extension after they restart.

### 5. Delegate one bounded task

In Claude Code, Codex, or Claude Desktop, ask the host agent:

```text
Use Hermit's run_task tool to add a focused test for <change> in this repository.
```

Hermit returns a task ID immediately. The host polls it with `check_task`, and
uses `reply_task` only if Hermit asks a question or permission decision. If the
executor is not ready, `run_task` does not create a task; it returns the same
specific diagnosis and setup command shown by `hermit doctor`.

#### Claude Desktop

Download `hermit-<version>.mcpb` from the matching GitHub Release and either
double-click it or choose **Settings → Extensions → Advanced settings → Install
Extension** in Claude Desktop. The extension uses the MCPB UV runtime, so it
installs Hermit's matching PyPI dependency without requiring a global Python
installation. It creates `~/.hermit/settings.json` on first launch. It supports
Claude Desktop on macOS and Windows; network access is required the first time
UV resolves the Hermit package. The installation screen optionally accepts an
executor model, OpenAI-compatible base URL, and API key; these values are held
by Claude Desktop and applied only to Hermit's MCP process, rather than written
to `settings.json`. Leave them blank to keep existing Hermit/Ollama settings.

## Use

Ask Claude Code, Codex, or Claude Desktop to delegate a scoped repository task
to Hermit. The MCP server exposes four task-lifecycle tools:

- `run_task(task, cwd, model?, max_turns?)`
- `check_task(task_id)`
- `reply_task(task_id, message)`
- `cancel_task(task_id)`

`run_task` starts a background task. Poll with `check_task`; if Hermit needs
input or a permission decision, reply through `reply_task`.

Hermit also supplies a small server instruction that recommends delegation for
bounded implementation, debugging, test, and maintenance work. It is guidance,
not a hidden autopilot: the host still owns the decision to delegate.

## Quality and multi-agent work

`run_task` defaults to `strategy: "single"`: one low-cost executor, with no
quality trade-off from orchestration. For a complex refactor, migration, or
security-sensitive change, the host can use `strategy: "auto"`. Hermit then
runs a read-only planner, one writing executor, and a read-only reviewer.

There are never parallel writing agents. If the reviewer does not return
`VERDICT: PASS`, Hermit returns `needs_review` instead of `done`; the host gets
the execution result and review findings together. Users can make `auto` their
local default in `~/.hermit/settings.json`:

```json
{
  "orchestration": {
    "mode": "auto",
    "max_agents": 3,
    "allow_parallel_writes": false
  }
}
```

## Configuration

Settings live at `~/.hermit/settings.json`. `hermit configure` is the preferred
way to configure a remote executor because it persists an environment-variable
reference rather than an API key. The default routing tries a configured GLM
provider first, then a locally installed Ollama model:

```json
{
  "routing": {
    "priority_models": [
      {"model": "glm-5.1"},
      {"model": "qwen3-coder:30b"}
    ]
  }
}
```

Use Ollama for a local executor (no per-token API cost) or any provider that
offers the OpenAI-compatible Chat Completions API with tool calling. Give a
custom endpoint an explicit provider profile; model names never need to match
a built-in prefix:

```json
{
  "providers": {
    "budget-provider": {
      "base_url": "https://llm.example.com/v1",
      "api_key_env": "BUDGET_PROVIDER_API_KEY"
    }
  },
  "routing": {
    "priority_models": [
      {"model": "coder-small", "provider": "budget-provider"},
      {"model": "qwen3-coder:30b"}
    ]
  }
}
```

Codex is a supported MCP host; it is not part of the default executor fallback
chain.

## Architecture

```text
Claude Code or Codex
        │ MCP over stdio
        ▼
  hermit mcp-server
        │ REST + task status
        ▼
 FastAPI gateway (loopback)
        ▼
 AgentLoop → repository tools → local/flat-rate LLM
```

The gateway owns background execution, cancellation, permission waits, model
routing, and task state. The MCP process stays small and transports only the
four public task operations.

## Development

```bash
.venv/bin/python -m pytest tests/
```

Hermit is MIT licensed and currently in alpha.
