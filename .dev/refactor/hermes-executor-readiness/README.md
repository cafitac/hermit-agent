# Hermes Executor Readiness Plan

> Trigger phrase for future sessions: if the user asks "Hermes executor 준비", "Claude/Codex/Hermes executor readiness", "이 프로젝트 다음 작업", or "문서 보고 이어서 진행", read this file first, then the PR-specific file for the next incomplete PR.

## Current repo baseline

Repository: `/Users/reddit/Project/hermit-agent`

Current base at time of writing:
- branch: `main`
- HEAD observed: `6bf092f Merge pull request #66 from cafitac/release-sync/v0.3.65`
- working tree was clean before writing this planning set
- latest release observed: `v0.3.65`

Verification already run:
- `.venv/bin/python -m pytest tests/test_orchestrator_contracts.py tests/test_orchestrator_prompt_mapping.py tests/test_hermes_orchestrator_adapter.py -q`
  - expected/current: `10 passed`
- `.venv/bin/python -m pytest tests/ -q`
  - expected/current: `1063 passed`

Important local Hermes observation:
- `command -v hermes` returned `/Users/reddit/.local/bin/hermes`
- `hermes mcp list` returned no configured MCP servers
- `hermit doctor` reported `WARN Hermes MCP: hermit-channel missing`
- `.venv/bin/python -m hermit_agent install --test-hermes-mcp` initially incorrectly reported `passed` because Hermes CLI printed `Server 'hermit-channel' not found in config.` while returning exit code 0; PR-01 is intended to make that output fail truthfully.
- direct `hermes mcp test hermit-channel` printed `✗ Server 'hermit-channel' not found in config.` while returning exit code 0

This means the current `run_hermes_mcp_connection_test()` is not trustworthy: it treats return code 0 as success even when Hermes reports that the server is missing.

## Product goal

Hermit should be a reliable executor lane for these orchestrators:

1. Claude Code
   - Claude Code remains planner/reviewer.
   - Hermit executes mechanical repo work through MCP tools.
   - Existing `-hermit` command family remains green.

2. Codex
   - Codex remains planner/orchestrator when desired.
   - Existing codex-channels / app-server / ask-MCP paths remain green.
   - No surprise hosted-model fallback is introduced.

3. Hermes Agent
   - Hermes remains planner/orchestrator, memory/skills/chat surface, and provider/auth owner.
   - Hermit is invoked as an MCP executor through `hermit-channel`.
   - Setup does not require OpenAI API keys when Hermes is configured via OpenAI Codex/ChatGPT OAuth.
   - The user can verify readiness with commands that fail when the integration is actually broken.

## Definition of done

Do not claim "Claude Code / Codex / Hermes executor readiness is complete" until all of these are true:

- Full repo test suite passes with `.venv/bin/python -m pytest tests/ -q`.
- `hermit install --test-hermes-mcp` fails when `hermit-channel` is missing, even if Hermes exits 0.
- `hermit install --fix-hermes-mcp` is idempotent and registers `hermit-channel -> hermit mcp-server` through the Hermes CLI.
- `hermit doctor` agrees with `hermes mcp list` and does not report a false PASS.
- A live Hermes MCP probe succeeds only after the server is registered.
- At least one tiny Hermit task can be invoked through the same MCP server surface used by Hermes, or the limitation is explicitly documented as not yet ready.
- Claude Code and Codex regression tests remain green after Hermes changes.
- Public docs distinguish stable behavior from experimental / adapter-in-progress behavior.

## Architecture direction

Keep the existing working runtime paths while extracting a neutral adapter boundary in safe slices.

Current implemented adapter pieces:
- `hermit_agent/orchestrators/contracts.py`
  - neutral DTO/protocol definitions
- `hermit_agent/orchestrators/hermes.py`
  - thin Hermes setup/doctor/live-smoke wrapper
  - runtime lifecycle methods intentionally raise `NotImplementedError`
- `hermit_agent/orchestrators/prompts.py`
  - runtime `InteractivePrompt` ↔ adapter `InteractivePrompt` mapping
  - `PromptReply` helper

Important current gap:
- `HermesMcpAdapter.submit_task()` is not implemented.
- `HermesMcpAdapter.emit_event()` is not implemented.
- `HermesMcpAdapter.wait_for_reply()` is not implemented.
- `HermesMcpAdapter.cancel()` is not implemented.

This is acceptable only if the canonical Hermes runtime remains the existing MCP server path and the adapter is documented as install/doctor-only. If the target architecture requires all orchestrators behind `OrchestratorAdapter`, later PRs must wire those lifecycle methods to the MCP/gateway task proxy.

## PR sequence

Implement in order. Each PR should be small, merged, released/synced if this repo's release automation requires it, and verified before moving to the next PR.

1. PR-01: Fix Hermes live-smoke truthfulness
   - File: `pr-01-hermes-live-smoke-truthfulness.md`
   - Fix false positive in `run_hermes_mcp_connection_test()`.

2. PR-02: Prove Hermes MCP registration and round-trip readiness
   - File: `pr-02-hermes-mcp-registration-roundtrip.md`
   - Make registration/list/doctor/test behavior internally consistent and document the real smoke path.

3. PR-03: Map gateway/MCP task lifecycle into neutral `TaskEvent`
   - File: `pr-03-task-event-mapping.md`
   - Add pure mapping helpers before rewiring runtime delivery.

4. PR-04: Add Claude and Codex adapter wrappers for install/health
   - File: `pr-04-claude-codex-adapter-wrappers.md`
   - Bring existing Claude/Codex setup diagnostics to the same adapter DTO layer as Hermes.

5. PR-05: Decide and implement runtime adapter boundary
   - File: `pr-05-runtime-delivery-boundary.md`
   - Either wire lifecycle methods behind adapters or explicitly narrow the adapter scope and document MCP server as canonical runtime.

6. PR-06: Public readiness docs and release hardening
   - File: `pr-06-public-readiness-docs-release.md`
   - Update README/docs only after behavior is verified.

## Working rules

- Do not modify `src/`, `claw-code-main/`, or `hermes-agent/` reference repos.
- Prefer `.dev/` for AI planning documents; promote to `docs/` only after behavior is implemented and verified.
- Preserve dirty worktrees. Check `git status --short --branch` before edits.
- Use the repo venv: `.venv/bin/python -m pytest ...`.
- Use TDD for code PRs: write failing test, observe RED, implement, observe GREEN.
- Keep print-only commands non-mutating.
- Keep mutation commands explicit (`--fix-*`) and idempotent.
- Do not introduce Anthropic or OpenAI API-key requirements for Hermes support.
- Do not silently add hosted Codex/OpenAI models to automatic executor routing.

## First command sequence for a future session

```bash
cd /Users/reddit/Project/hermit-agent
git status --short --branch
sed -n '1,240p' .dev/refactor/hermes-executor-readiness/README.md
sed -n '1,240p' .dev/refactor/hermes-executor-readiness/pr-01-hermes-live-smoke-truthfulness.md
.venv/bin/python -m pytest tests/test_install_flow.py tests/test_doctor.py tests/test_hermes_orchestrator_adapter.py -q
```

If PR-01 is already merged, read the next PR file in numeric order and start from its "First implementation steps" section.
