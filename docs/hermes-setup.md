# Register HermitAgent as a Hermes Agent MCP executor

This guide is specifically for Hermes Agent. If you want Claude Code or Codex instead, use `docs/cc-setup.md` or `docs/codex-setup.md`.

## What gets wired

Hermit exposes a stdio MCP server at:

```bash
hermit mcp-server
```

For Hermes Agent, the important integration surface is the MCP server name `hermit-channel`. Once registered, Hermes can call Hermit's MCP tools such as `run_task`, `reply_task`, `check_task`, and `cancel_task`.

Current boundary note:
- The live task runtime stays on Hermit's existing MCP server path.
- Hermes-facing setup helpers are for registration, repair, and smoke checks only.

## 1. Install Hermit

```bash
npm install -g @cafitac/hermit-agent
hermit
```

Requires Node.js 20+ and Python 3.11+.

## 2. Print the non-mutating registration command

Start with the safe path:

```bash
hermit install --print-hermes-mcp-config
```

This prints the exact `hermes mcp add ...` command for `hermit-channel` without editing `~/.hermes`.

## 3. Register Hermit with Hermes Agent

You have two supported options.

### Option A — explicit manual registration

Run the command printed by the previous step. It should look like:

```bash
hermes mcp add hermit-channel --command hermit --args mcp-server
```

### Option B — explicit Hermit-assisted repair/registration

If you want Hermit to call the Hermes CLI for you:

```bash
hermit install --fix-hermes-mcp
```

This path is intentional and explicit: Hermit does not silently edit Hermes config by default.

## 4. Verify the live MCP wiring

Run the bounded live probe:

```bash
hermit install --test-hermes-mcp
```

If you want an isolated Hermes config during registration, smoke, or doctor checks, point Hermit at a separate home:

```bash
hermit install --fix-hermes-mcp --hermes-home /tmp/hermes-home
hermit install --test-hermes-mcp --hermes-home /tmp/hermes-home
hermit doctor --hermes-home /tmp/hermes-home
```

Under the hood this executes Hermes Agent's live MCP check for `hermit-channel` without mutating config beyond the explicit `--fix-hermes-mcp` path.

You can also inspect Hermes directly:

```bash
hermes mcp list
hermes mcp test hermit-channel
```

## 5. Troubleshooting

| Symptom | What to do |
|---|---|
| `hermit install --print-hermes-mcp-config` shows setup text but Hermes still cannot see Hermit | Run the printed `hermes mcp add ...` command or `hermit install --fix-hermes-mcp`, then restart Hermes sessions that should load MCP servers |
| `hermit install --test-hermes-mcp` fails | Run `hermit install --fix-hermes-mcp`, re-check `hermes mcp list`, then retry the test |
| `hermes mcp test hermit-channel` prints an error even though the shell exit code looks successful | Prefer `hermit install --test-hermes-mcp`; Hermit treats known failure text as a failed smoke even when Hermes itself exits 0 |
| You want OAuth-based OpenAI Codex / ChatGPT in Hermes | Configure Hermes itself for `openai-codex` / ChatGPT OAuth; Hermit's MCP registration does not require introducing OpenAI API keys |

## 6. What this does not change

- It does not replace Hermes Agent as your planner.
- It does not require Anthropic configuration.
- It does not require OpenAI API keys just to register Hermit as an MCP executor.
- It does not change Claude Code or Codex integrations.

## Suggested operator flow

```bash
npm install -g @cafitac/hermit-agent
hermit install --print-hermes-mcp-config
hermes mcp add hermit-channel --command hermit --args mcp-server
hermit install --test-hermes-mcp
```

If the manual registration is already done or drifted, swap the middle step for:

```bash
hermit install --fix-hermes-mcp
```