# Register HermitAgent as a Claude Code MCP sub-agent

This is the setup that makes `/feature-develop-hermit`, `/code-apply-hermit`, etc. work from inside Claude Code. Five minutes, no Docker.

## 1. Install and start the gateway

```bash
./install.sh          # one-shot: venv, deps, default settings
./bin/gateway.sh --daemon # FastAPI relay on :8765
```

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
| `mcp__hermit__run_task` hangs | Gateway not running (`./bin/gateway.sh --daemon`) or wrong `gateway_url` |
| Claude Code shows no push notifications | Start Claude Code with `--dangerously-load-development-channels server:hermit-channel` |
| Wrong model picked | `HERMIT_MODEL` env or the `model` key in settings — names containing `:` route to ollama, anything else goes through `llm_url` |
| MCP server won't start | `./bin/mcp-server.sh` alone should print `ready`; if it fails, run with `HERMIT_DEBUG=1` |

## How tokens actually get saved

```
/feature-develop         → pure Claude: reads files, runs pytest, writes commit msg, etc.
/feature-develop-hermit  → Claude interviews + plans (small tokens)
                           run_task → Hermit does the edits and tests (executor tokens)
                           Claude only sees the final summary, not the grunt-work output
```

The Hermit MCP server truncates long task results (head 2000 + tail 1000 by default, configurable via `check_task(full=true)` when Claude actually needs the full log), so the orchestrator session never balloons.
