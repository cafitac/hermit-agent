# HermitAgent

> **Run Claude Code cheaper with Hermit as executor — Codex first, then z.ai/local fallback — while Claude stays the orchestrator.**

HermitAgent plugs into Claude Code as an MCP sub-agent. Claude keeps doing what it is best at — planning, interviewing, code review — and delegates the high-token grunt work (file edits, test runs, commit/push, refactors) to a cheap executor (ollama on your laptop, or a flat-rate z.ai subscription).

## v0.2.x highlights

- **Codex support is first-class**: Hermit can run tasks via Codex (`gpt-5.3-codex`) through the gateway.
- **Auto model routing when `model` is omitted**: `codex -> z.ai (glm) -> local ollama`.
- **Explicit model requests are strict**: if you ask for a specific model and it is unavailable, Hermit returns a clear unavailable error instead of silently switching providers.
- **MCP + gateway auto-start**: `bin/mcp-server.sh` now ensures the local gateway is up, so Claude Code/Codex startup is simpler.

```
┌──────────────┐   MCP   ┌──────────────┐   any OpenAI-compatible   ┌───────┐
│  Claude Code │ ──────▶ │  HermitAgent │ ────────────────────────▶ │  LLM  │
│ (planner)    │         │  (executor)  │                           └───────┘
└──────────────┘         └──────────────┘
     $$$                      ~$0 / flat-rate
```

## Why

Claude Code is great, but a `/feature-develop` session easily burns 100k+ Claude tokens on mechanical work — reading files, running `pytest`, formatting diffs, writing conventional-commit messages — that any competent code model can do. HermitAgent exposes three MCP tools (`run_task`, `reply_task`, `check_task`) so Claude Code can delegate whole skills to a cheaper model while the user stays in the familiar Claude Code UI.

## The pattern

![demo](assets/demo.gif)

## How much it actually saves

**Measured numbers live under [`benchmarks/results/`](benchmarks/results/)** — each file is one independent run pair.

We deliberately don't publish a single marketing percentage here. Savings depend on the task, the repo, and the executor you choose; a headline number without that context is noise. If you want a reproducible datapoint:

1. `cp -r benchmarks/todo-api/starter /tmp/cc-run && cp -r benchmarks/todo-api/starter /tmp/cc-hermit-run`
2. Run `/feature-develop <task>` in one, `/feature-develop-hermit <task>` in the other (task spec: [`benchmarks/todo-api/TASK.md`](benchmarks/todo-api/TASK.md)).
3. Feed the two Claude Code session logs into [`scripts/measure-savings.sh`](scripts/measure-savings.sh) — it prints a markdown table you can paste into `benchmarks/results/`.

Full protocol: [`docs/measure-savings.md`](docs/measure-savings.md). Executor cost is treated as \$0 (ollama = free, z.ai / GLM = flat-rate); what we compare is Claude-side tokens and USD.

## What it gives you

The product is the **pattern**, not any specific skill:

> Claude does reasoning, judgment, and quality gates.
> A cheap local / flat-rate executor does the grunt work.
> They talk to each other over MCP, so the switch is one word in a slash command.

The repo ships this pattern as four **example** skills under `.claude/commands/` so you can see it in action and fork them into whatever workflow you already have:

- `/feature-develop-hermit` — Claude interviews, Hermit implements and tests
- `/code-apply-hermit` — Claude reads the PR review, Hermit applies every line
- `/code-polish-hermit` — Claude picks what to polish, Hermit runs the lint/test loop
- `/code-push-hermit` — Claude writes the PR description, Hermit does the commit/push

These are **reference implementations**, tuned for the author's own workflow (GitHub PR-centric). The goal is for Claude to stay on the "small Claude tokens, big quality impact" work — interviews, review, final verification — and for everything high-volume / mechanical (Read × N, Edit × N, Bash/pytest loops, commit message writing) to land on Hermit. Write your own `-hermit` variant for the skills you actually live in; the [docs/hermit-variants.md](docs/hermit-variants.md) "add your own" recipe is a few steps.

Everything else in the repo is there to make that pattern work cleanly:

- **MCP server** (`run_task` / `reply_task` / `check_task`) with bidirectional conversation — Hermit can ask Claude mid-task
- **Skill compatibility** — same `SKILL.md` format and YAML frontmatter as Claude Code; skills under `~/.claude/skills/` are shared read-only
- **Progressive-disclosure rule system** — foundational rules stay auto-injected, contextual rules are on-demand skills (cuts session prefix from ~12k to ~3k tokens)
- **Gateway** (FastAPI + SSE) in front of the executor LLM — 429 fail-fast + failover, cache hints, dashboard at `:8765`
- **Model routing by name + auto chain** — explicit names route by provider (`gpt-*-codex` → Codex, `glm-*` → z.ai, `name:tag` → local ollama); omitted model auto-routes `codex -> z.ai -> local`
- **Permission floor** — `.env`, `*.pem`, `*.key`, `credentials*` blocked across every mode (even YOLO)
- **Self-learning skills** with model-aware lifecycles (validated-on models, 30-day auto-deprecation, `needs_review` on model swap)
- **Optional standalone TUI** (React + Ink) for when you want to use Hermit without Claude Code in the loop

## How is this different from …?

| Project | Pattern | Trade-off |
|---|---|---|
| **claude-code-router** | Redirects all CC traffic to another provider | You lose Claude quality; the "Claude Code" session is really the local model |
| **LiteLLM** | Generic multi-provider proxy | Not coding-specific, no understanding of CC workflow |
| **OpenHands / aider** | Standalone agent, replaces Claude Code | Full migration away from CC; big UX change |
| **Anthropic Agent SDK** | Official sub-agent framework | DIY: you still write the executor, the local-model wiring, the MCP glue |
| **HermitAgent** | Claude **stays** the orchestrator; Hermit is the executor | Narrower scope, but drop-in: `/foo` → `/foo-hermit` |

If you don't use Claude Code, you don't need HermitAgent. If you do, and the monthly bill or the rate limits are a problem, this is what it is for.

### Where the project is heading

The bundled skills still give Claude the full interview phase before delegating. The direction this project is moving in is the opposite: **Claude does only the final verification pass** — the executor does the interview, the plan, the implementation, the tests, the commit — and Claude is only woken up at the end to reject, accept, or ask for a narrow revision. The less Claude does, the more of the bill disappears. The existing `-hermit` skills are the conservative checkpoint on that spectrum; your own variants can push further.

## Install

```bash
git clone https://github.com/cafitac/hermit-agent.git
cd hermit-agent
./install.sh
```

What the installer does automatically:

- Creates a project-local `.venv`, bootstraps `uv` inside it, and runs `uv pip install -e '.[test]'`.
- Writes a default `~/.hermit/settings.json` (model `glm-5.1`, gateway URL `http://localhost:8765`, etc.).
- **Prompts `Generate a random gateway API key now?`** If you accept, it applies the schema in `hermit_agent/gateway/migrations/001_initial.sql` to `~/.hermit/gateway.db`, inserts a freshly-generated `hermit-mcp-<random>` key, and patches `gateway_api_key` in your settings file.
- **Prompts `Pull a local coding model via ollama?`** (skipped automatically if `ollama` is not installed). Accepting pulls `qwen3-coder:30b` (~18 GB).
- Symlinks the four bundled `-hermit` slash commands into `~/.claude/commands/`.
- **Prompts `Register Hermit MCP server in ~/.claude.json?`** with three choices: (a) project-specific, (b) user-wide, (c) skip. On accept, merges a `hermit-channel` stdio entry pointing at `./bin/mcp-server.sh` into `~/.claude.json` (backup: `~/.claude.json.backup-<ts>`). Safe on re-runs — an identical entry is detected and left alone. That launcher now auto-starts the local gateway on demand (and skips the start when the gateway is already healthy).
- **Prompts `Add hermit alias to <rc-file>?`** so you can run `hermit` from any shell. If an existing alias points to an old path (e.g. before the `bin/` move), the installer offers to update it.
- Prints any "Pending manual steps" at the end — e.g. a reminder to launch Claude Code with `--dangerously-load-development-channels server:hermit-channel`.

Useful flags:

```bash
./install.sh --no-api-key        # skip the API key prompt (use placeholder)
./install.sh --no-ollama         # skip the ollama prompt
./install.sh --skip-venv         # reuse an existing .venv
./install.sh --no-mcp-register   # skip the ~/.claude.json registration prompt
./install.sh --no-alias          # skip the shell-rc alias prompt
```

Every prompt is idempotent: re-running the installer detects the existing API key, MCP entry, alias, and ollama model and reports them unchanged instead of duplicating.

To reverse everything: `./uninstall.sh` walks back through the same steps with per-item prompts (`--yes` accepts all; `--keep-data` leaves `~/.hermit/` alone). Ollama models are never deleted — remove manually with `ollama rm <model>`.

The `hermit` launcher transparently starts the gateway daemon if it isn't already running (`HERMIT_AUTO_GATEWAY=0` opts out), so you never need to remember to run `./bin/gateway.sh --daemon` first. The MCP launcher (`./bin/mcp-server.sh`) now does the same check-and-start flow, which makes both Claude Code and Codex able to bring up the full Hermit stack from the MCP entrypoint alone.

### Pick an executor LLM

**ollama (local, $0)** — either accept the installer prompt, or:

```bash
brew install ollama
ollama pull qwen3-coder:30b
```

**z.ai Coding Plan (flat-rate subscription)** — add your z.ai key to `~/.hermit/settings.json`:

```json
{
  "gateway_url": "http://localhost:8765",
  "gateway_api_key": "hermit-mcp-…",
  "model": "glm-5.1",
  "providers": {
    "z.ai": {
      "base_url": "https://api.z.ai/api/coding/paas/v4",
      "api_key": "<your z.ai key>",
      "anthropic_base_url": "https://api.z.ai/api/anthropic"
    }
  }
}
```

Two keys, two layers: `gateway_api_key` authenticates clients against the local Hermit gateway, and `providers[<slug>].api_key` is the gateway's own credential for talking to the upstream platform. Add a new provider by dropping another block into `providers` — e.g. `providers["anthropic"]` with a base_url + api_key.

### Skipped the API key prompt?

Either re-run `./install.sh` (it detects a placeholder and re-prompts), or mint one manually — see [docs/cc-setup.md § 2](docs/cc-setup.md). Hermit will refuse to run until `gateway_api_key` is a real value, not `CHANGE_ME_AFTER_FIRST_RUN`.

### Wire it into Claude Code

If you accepted the installer's MCP registration prompt, the `hermit-channel` stdio entry is already in `~/.claude.json` — the remaining piece is launching Claude Code with `--dangerously-load-development-channels server:hermit-channel` so the channel capability is enabled. A shell alias works well:

```bash
alias cc='claude --dangerously-load-development-channels server:hermit-channel'
```

If you skipped the registration prompt (or want to adjust the scope later), see [docs/cc-setup.md § 3](docs/cc-setup.md) for the exact `~/.claude.json` block.

## Quick start — CC + Hermit (the recommended shape)

```bash
./bin/mcp-server.sh               # auto-starts the gateway if needed, then serves MCP stdio
```

Then in Claude Code:

```
/feature-develop-hermit <ticket-or-short-task>
```

Claude interviews you about the ticket, writes the plan, and delegates the implementation to Hermit over MCP. You watch Hermit's progress in the Claude Code session; the executor tokens never hit your Claude bill.

### Standalone (no Claude Code)

```bash
./bin/hermit.sh "fix the flaky test in tests/test_api.py"   # one-shot CLI
./bin/hermit.sh                                              # TUI (needs HERMIT_UI_DIR)
```

### Two API endpoints

The gateway exposes the same upstream providers behind two wire-format-specific paths. Model routing (`name:tag` → local ollama, `glm-*` → z.ai, extensible) is identical between them.

- **`/v1/chat/completions` — OpenAI-native** (primary sharing surface)
  Used by the `hermit` CLI, anything speaking the OpenAI SDK, and ngrok-exposed friends. Tier-gated via per-key platform ACL.
  ```python
  from openai import OpenAI
  client = OpenAI(base_url="https://<ngrok>.ngrok.app/v1", api_key="<friend-key>")
  ```

- **`/anthropic/v1/messages` — Anthropic-native** *(alternative, not recommended as the Claude Code path)*
  Enables pointing Claude Code at the gateway via `ANTHROPIC_BASE_URL=http://localhost:8765/anthropic` + `ANTHROPIC_AUTH_TOKEN=<gateway-key>`. z.ai is passthrough; ollama goes through a text-only Anthropic↔OpenAI translator (tool_use returns 400 in v1).
  **Use only if you understand the tradeoff.** This bypasses HermitAgent entirely — Claude Code drives and your CC-side tools/permissions are all that apply. The recommended integration remains `CC → MCP (hermit-channel) → HermitAgent`, which `install.sh` already sets up.

**Platform ACL (operator vs friend):**
```
Operator key (install.sh --generate-api-key, the default)
  → platforms: local, z.ai, anthropic, codex   (full access)

Friend key (install.sh --generate-friend-key)
  → platforms: local                            (local ollama only; 403 for glm-*)
```

A key with zero rows in `api_key_platform` is denied everything (default-deny).

### Configuration

Priority: CLI flag > env var > `<cwd>/.hermit/settings.json` > `~/.hermit/settings.json` > defaults.

If `model` is omitted in a task request, Hermit auto-routes in this order: **Codex -> z.ai -> local ollama**.

```json
{
  "gateway_url": "http://localhost:8765",
  "gateway_api_key": "hermit-mcp-…",
  "model": "glm-5.1",
  "response_language": "auto",
  "compact_instructions": "",
  "ollama_max_loaded": 1,
  "external_max_concurrent": 10
}
```

`ollama_max_loaded` is how many distinct models the gateway lets ollama hold in memory simultaneously — if a request targets a not-yet-loaded model while the budget is already full, the gateway returns **503** with `Retry-After` instead of letting ollama swap itself into an OOM. `external_max_concurrent` caps in-flight requests to external providers (z.ai, OpenAI, …); excess requests queue rather than fail. This is the replacement for the old `ollama-proxy` — the gateway itself is safe to expose (e.g. via ngrok).

**Field semantics after the proxy refactor:**
- `gateway_url` / `gateway_api_key` — **client-facing**. What the `hermit` CLI (and any other client) sends to authenticate against the local gateway.
- `providers[<slug>]` — **gateway-internal, upstream**. Per-platform block the gateway uses to reach z.ai / Anthropic / OpenAI / etc. on your behalf. Clients never see these. Adding a new provider is one JSON block — the adapter layer picks it up by slug.

## Architecture (short version)

- **AgentLoop** — LLM turn, tool call, result, compact when context fills
- **Gateway** — FastAPI layer in front of the executor. Classifier, routing, failover, web dashboard
- **MCP server** — exposes `run_task` / `reply_task` / `check_task` / `cancel_task` for Claude Code
- **Channel notifications** — `notifications/claude/channel` frames emitted inline by the Python MCP server; Claude Code renders them as `<channel source="hermit-channel">` blocks
- **Skills** — markdown with YAML frontmatter, hot-loaded at session start, compatible with `~/.claude/skills/`

## Layout

```
hermit_agent/                # agent, loop, tools, gateway, MCP, skills
.claude/                     # this repo's own Claude Code config
scripts/harness/             # harness tooling (cc-learner.py, etc.)
tests/                       # pytest suite
```

## Status

Early, working, single-author. MIT. No release cadence. No roadmap promises. Clone, read the code, open an issue if something is broken.

## Running tests

```bash
pytest    # conftest.py auto-excludes ollama-dependent tests
```

## Boundaries

- Hermit does not modify `~/.claude/` — it only reads `~/.claude/skills/` for cross-tool skill reuse
- Hermit does not require Claude Code; it just shines brightest as its sub-agent
- Nothing phones home. Everything runs locally or through the LLM endpoint you configure

## License

MIT — see [LICENSE](LICENSE).

## See also

- **[docs/cc-setup.md](docs/cc-setup.md)** — registering Hermit as a Claude Code MCP sub-agent
- **[docs/hermit-variants.md](docs/hermit-variants.md)** — the `-hermit` skill family in detail
- **[docs/measure-savings.md](docs/measure-savings.md)** — cost-savings measurement protocol
- **[benchmarks/](benchmarks/)** — reproducible task specs and community datapoints
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution guide
- [.dev/](.dev/) — internal design notes
