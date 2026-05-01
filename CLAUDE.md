# HermitAgent Project — Claude Code Context

## Project Overview
HermitAgent is a conversational coding agent similar to Claude Code. Python 3.11+, FastAPI.
- `hermit_agent/` — agent core (loop, MCP server, tools, gateway, hooks)
- `src/` — Claude Code original source (read-only reference, no modifications, additions, or deletions)
- `claw-code-main/`, `hermes-agent/` — external reference repos (read-only)

## 3-Layer Harness
Layer A = this file + `.claude/` (CC working on this repo). Layer B = `HERMIT.md` + `hermit_agent/` (HermitAgent's own features). Layer C = env/args passed when HermitAgent spawns CC. Layer A changes go here; Layer B/C changes go inside `hermit_agent/`. Do not mix layers.

## Key Modules
- `hermit_agent/loop.py` — message loop & guardrail
- `hermit_agent/mcp_server.py` — MCP server (run_task/reply_task/check_task)
- `hermit_agent/gateway/__init__.py` — AI Gateway FastAPI app

## Tests
```bash
.venv/bin/python -m pytest tests/   # conftest.py auto-excludes Ollama-dependent tests
```

## Run Scripts
- `./bin/gateway.sh` — start Gateway server
- `./bin/mcp-server.sh` — start MCP server
- `./bin/hermit.sh` — standalone Hermit CLI/TUI

## Session Routine
Plan first (`/ralplan`), verify before exit (`.venv/bin/python -m pytest tests/`), wrap with `/session-wrap`.

## Hermit MCP
Register task_id immediately after run_task/check_task:
```python
hermit-channel.register_task(task_id)
```
Full rules: `/hermit-mcp` skill.

## CC vs HermitAgent Delegation
`-hermit` variant commands use CC as orchestrator + HermitAgent as executor (saves CC tokens). Key variants: `/feature-develop-hermit`, `/code-apply-hermit`, `/code-push-hermit`, `/code-polish-hermit`. Full table: `docs/delegation.md`.

## Document Management
- `docs/` — human-managed (read-only for AI without explicit approval)
- `.dev/` — AI-managed (analysis, spec drafts, session traces)

## Learned Feedback Skills
Managed by `~/.claude/scripts/cc-learner.py`. Auto-injected at session start. See `.dev/learner-spec.md`.

## Prohibited
- `src/` — absolutely no modifications (Claude Code original reference only)
- No new Django/React projects inside this repo
- No harness config embedded in Gateway
