# Register HermitAgent as a Claude Code MCP sub-agent

This is the setup that makes `/feature-develop-hermit`, `/code-apply-hermit`, etc. work from inside Claude Code. Five minutes, no Docker.

## 1. Install and initialize the gateway

```bash
./install.sh          # one-shot: venv, deps, default settings
```

`./bin/mcp-server.sh` now auto-starts the gateway when Claude Code or Codex launches the MCP server, so the explicit `./bin/gateway.sh --daemon` step is optional. It is still handy when you want to warm the relay up manually before connecting a client.

Verify:

```bash
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
```

You should see `"status": "operational"` and the LLM endpoint Hermit is relaying to.

## 2. Mint a gateway API key

Hermit's gateway authenticates every MCP call. Issue a key once:

```bash
sqlite3 ~/.hermit/gateway.db \
  "INSERT INTO api_keys(token, owner, enabled, created_at) VALUES ('hermit-mcp-$(openssl rand -base64 24 | tr -dc A-Za-z0-9 | head -c 32)', 'local', 1, datetime('now'));"
sqlite3 ~/.hermit/gateway.db "SELECT token FROM api_keys ORDER BY rowid DESC LIMIT 1;"
```

Copy the printed token into `~/.hermit/settings.json`:

```json
{
  "gateway_url": "http://localhost:8765",
  "gateway_api_key": "hermit-mcp-…",
  "model": "glm-5.1"
}
```

## 3. Register the MCP server in Claude Code

### Option A — scoped to this project only (recommended)

Edit `~/.claude.json` and add under the project's `mcpServers` block:

```json
{
  "projects": {
    "/absolute/path/to/your/repo": {
      "mcpServers": {
        "hermit-channel": {
          "type": "stdio",
          "command": "/absolute/path/to/hermit-agent/bin/mcp-server.sh"
        }
      }
    }
  }
}
```

A single Python MCP server exposed under the name `hermit-channel` handles both the task delegation tools (`run_task` / `reply_task` / `check_task` / `register_task`) and the push-notification channel (`waiting` / `running` / `done`). The name is intentionally `hermit-channel` so the `--dangerously-load-development-channels server:hermit-channel` flag (next step) picks it up as a development channel.

For operators, the important thing is simple: Claude Code or Codex should connect to **`hermit-channel`**. If you inspect MCP state, that is the name you should expect to see. Any extra local assets Hermit creates for async approvals or free-text replies are internal implementation details, not the primary integration surface.

### Option B — user-wide

Same JSON, but under the top-level `mcpServers` key instead of nested under a project.

### Load dev channels

Claude Code needs to be told to accept development MCP channels:

```bash
claude --dangerously-load-development-channels server:hermit-channel
```

Put that alias in your shell rc if you want it by default.

## 4. Verify from Claude Code

In a Claude Code session:

```
/mcp
```

You should see `hermit-channel` listed as connected. Then:

```
mcp__hermit__run_task(task="say hello and exit", background=false)
```

The task should return `{"status": "done", "result": "…"}`.

## 5. Try the real thing

```
/feature-develop-hermit <ticket or short description>
```

Claude will interview you briefly, write a plan, then delegate implementation to Hermit. You watch the progress in the Claude Code session; executor tokens go to your Hermit LLM (ollama = free, z.ai = flat-rate), not your Claude bill.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/mcp` shows `hermit` as failed | Check `~/.hermit/gateway.log` for a 401 or connection refused; re-mint the API key |
| `mcp__hermit__run_task` hangs | Auto-start may have failed or `gateway_url` is wrong; check `~/.hermit/gateway.log`, then try `./bin/gateway.sh --daemon` manually |
| Claude Code shows no push notifications | Start Claude Code with `--dangerously-load-development-channels server:hermit-channel` |
| Wrong model picked | `HERMIT_MODEL` env or the `model` / `routing.priority_models` keys in settings. Explicit routing: `gpt-*-codex` and `gpt-5.4` → Codex, `glm-*` → `providers["z.ai"]`, `name:tag` → ollama. If model is omitted, gateway follows `routing.priority_models` and skips providers that are not configured/installed. |
| MCP server won't start | `./bin/mcp-server.sh` now ensures the gateway first; if startup still fails, inspect `~/.hermit/mcp_server.log` and `~/.hermit/gateway.log` |

## How tokens actually get saved

```
/feature-develop         → pure Claude: reads files, runs pytest, writes commit msg, etc.
/feature-develop-hermit  → Claude interviews + plans (small tokens)
                           run_task → Hermit does the edits and tests (executor tokens)
                           Claude only sees the final summary, not the grunt-work output
```

The Hermit MCP server truncates long task results (head 2000 + tail 1000 by default, configurable via `check_task(full=true)` when Claude actually needs the full log), so the orchestrator session never balloons.

## Alternative: bypass MCP and point Claude Code at the gateway directly

The flow above (`CC → MCP hermit-channel → HermitAgent`) is the recommended integration, and `install.sh` configures exactly this. HermitAgent's gateway also exposes an Anthropic-native endpoint (`/anthropic/v1/messages`) that Claude Code can use directly — but this is an **alternative for advanced users**, not the sanctioned path.

To use it, set (for example in `~/.claude/settings.json` or a per-project env override — `install.sh` does NOT set these for you):

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8765/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "hermit-mcp-…",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.1",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.1-air",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.1"
  }
}
```

The gateway routes the incoming Anthropic request by model name: `glm-*` is proxied to z.ai's `/api/anthropic` natively; a `name:tag` (ollama) model is translated via HermitAgent's Anthropic↔OpenAI translator.

**Tradeoffs (important):**
- (+) You get the Claude Code UI talking to your chosen upstream.
- (−) Claude Code becomes just a chat UI — its built-in tools, permission modes, TodoWrite, and slash-command skills run against the upstream directly.
- (−) HermitAgent itself is not in the loop — none of its skills, hooks, session-wrap, or MCP task-queue features fire. You are effectively using the gateway as a plain reverse proxy.
- (−) Rate limits and token budgets follow the upstream (z.ai, ollama), not Anthropic's native quotas.
- (−) The ollama-via-Anthropic path currently rejects `tool_use` / `tool_result` content blocks with HTTP 400 (text-only translator in v1).

### OpenAI-SDK share via `/v1/chat/completions`

The OpenAI-native path is the better option when you want to hand inference out over the network — e.g. sharing local ollama with a collaborator via ngrok. Mint a platform-scoped friend key (`./install.sh --generate-friend-key` issues a `local`-only token) and connect with any OpenAI-compatible client:

```python
from openai import OpenAI
client = OpenAI(base_url="https://<ngrok>.ngrok.app/v1", api_key="<friend-key>")
client.chat.completions.create(model="qwen3-coder:30b", messages=[...])
```

The friend key gets 403 if it asks for a non-local model (e.g. `glm-5.1`); operator keys reach every platform in `api_key_platform`.
