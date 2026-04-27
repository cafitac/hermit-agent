# HermitAgent

[![Python tests](https://github.com/cafitac/hermit-agent/actions/workflows/python-tests.yml/badge.svg)](https://github.com/cafitac/hermit-agent/actions/workflows/python-tests.yml)
[![npm version](https://img.shields.io/npm/v/@cafitac/hermit-agent?cacheSeconds=300)](https://www.npmjs.com/package/@cafitac/hermit-agent)
[![PyPI version](https://img.shields.io/pypi/v/cafitac-hermit-agent?cacheSeconds=300)](https://pypi.org/project/cafitac-hermit-agent/)
[![npm downloads](https://img.shields.io/npm/dm/@cafitac/hermit-agent?cacheSeconds=300)](https://www.npmjs.com/package/@cafitac/hermit-agent)

> Run Claude Code or Codex cheaper — Hermit is an MCP executor that handles the high-token mechanical work while your orchestrator stays in charge.

```
┌──────────────┐
│  Claude Code │──┐
│  (planner)   │  │    ┌──────────────┐   any OpenAI-compatible   ┌───────┐
└──────────────┘  ├───▶│  HermitAgent │ ────────────────────────▶ │  LLM  │
                  │    │  (executor)  │                           └───────┘
┌──────────────┐  │    └──────────────┘
│    Codex     │──┘         ~$0 / flat-rate
│  (planner)   │
└──────────────┘
```

Claude Code or Codex stays the orchestrator — planning, interviewing, code review. Hermit takes the rest: file edits, test runs, commits, refactors, on a cheap local or flat-rate model via MCP. The switch is one word in a slash command: `/foo` → `/foo-hermit`.

## Install

```bash
npm install -g @cafitac/hermit-agent
hermit
```

Requires Node.js 20+ and Python 3.11+. The npm package bootstraps a managed Python runtime under `~/.hermit/` on first run — no repo checkout needed. If Claude Code or Codex integration is still missing, `hermit` will offer guided setup automatically. You can still run `hermit install` directly when you want to force the full setup/repair flow.

To upgrade: `hermit update`

## Quick start

```bash
hermit-mcp-server   # starts the gateway + MCP stdio server
```

Then in Claude Code:

```
/feature-develop-hermit <task>
```

Claude interviews, writes the plan, and delegates implementation to Hermit over MCP. Executor tokens never hit your orchestrator bill.

## Reference skills

Four example skills ship under `.claude/commands/`. Fork these into your own workflow:

| Command | Claude does | Hermit does |
|---|---|---|
| `/feature-develop-hermit` | interview + plan | implement + test |
| `/code-apply-hermit` | read PR review | apply every change |
| `/code-polish-hermit` | pick what to polish | lint/test loop |
| `/code-push-hermit` | write PR description | commit + push |

See [docs/hermit-variants.md](docs/hermit-variants.md) to add your own.

## Executor LLM

**ollama (local, free):**
```bash
brew install ollama && ollama pull qwen3-coder:30b
```

**z.ai (flat-rate subscription)** — add to `~/.hermit/settings.json`:
```json
{
  "providers": {
    "z.ai": {
      "base_url": "https://api.z.ai/api/coding/paas/v4",
      "api_key": "<your key>",
      "anthropic_base_url": "https://api.z.ai/api/anthropic"
    }
  }
}
```

## Configuration

`~/.hermit/settings.json` (created by `hermit install`):

```json
{
  "gateway_url": "http://localhost:8765",
  "gateway_api_key": "hermit-mcp-…",
  "model": "__auto__",
  "routing": {
    "priority_models": [
      {"model": "glm-5.1"},
      {"model": "qwen3-coder:30b"}
    ]
  }
}
```

`model` controls the default model for plain `hermit`. Set it to `__auto__` if you want plain `hermit` to follow the `routing.priority_models` order. `routing.priority_models` is the ordered fallback chain for auto-routing in gateway / interactive flows, and providers that are not configured or installed are skipped automatically. If `model` is a concrete name like `gpt-5.4`, plain `hermit` stays pinned to that model even if you reorder `priority_models`.

By default, `hermit install` now keeps Codex out of `routing.priority_models` and treats it as an explicit opt-in executor path instead of an automatic fallback. This is intentional: local / flat-rate executor models stay the safe default, while Codex remains available when a user explicitly pins it or adds it back to routing. That separation makes billing behavior more predictable, keeps executor defaults aligned with Hermit's "cheap mechanical work" role, and avoids surprising auto-routing onto a paid hosted model.

## Architecture

- **AgentLoop** — LLM turn → tool call → result → compact on context fill
- **Gateway** — FastAPI relay in front of the executor (routing, 429 failover, dashboard at `:8765`)
- **MCP server** — `run_task` / `reply_task` / `check_task` / `cancel_task`
- **TUI** — optional React+Ink terminal UI for standalone interactive sessions (`hermit`)

## Tests

```bash
.venv/bin/pytest tests/
```

## Status

Early, working, MIT. No release cadence guarantees.

## License

MIT — see [LICENSE](LICENSE).

## See also

- [docs/cc-setup.md](docs/cc-setup.md) — Claude Code MCP registration details
- [docs/hermit-variants.md](docs/hermit-variants.md) — the `-hermit` skill family
- [docs/measure-savings.md](docs/measure-savings.md) — cost-savings measurement protocol
- [CHANGELOG.md](CHANGELOG.md) — notable release and policy changes
- [benchmarks/](benchmarks/) — reproducible task specs and community datapoints
