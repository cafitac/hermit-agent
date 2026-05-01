# Hermes Integration Plan

## Goal

Make Hermit usable from Hermes Agent as a mechanical executor lane, while preserving the existing Claude Code and Codex integrations.

Target role split:

- Hermes Agent: planner/orchestrator, conversation, review, memory/skills, provider/auth policy.
- Hermit: executor for bounded repo mechanics: edits, tests, refactors, commits, and repeatable follow-through.

## Important Hermes facts

Hermes supports MCP servers through CLI commands such as:

```bash
hermes mcp add NAME --command ...
hermes mcp list
hermes mcp test NAME
hermes mcp configure NAME
```

Hermes also supports one-shot subprocess usage:

```bash
hermes chat -Q -q '<prompt>' --provider openai-codex --model gpt-5.5
```

For this project, Hermes support should not assume plain OpenAI API keys. Many users may run Hermes through OpenAI Codex / ChatGPT OAuth. Hermit must not introduce an implicit OpenAI API-key path during setup.

## Recommended path: MCP first

### Why MCP first

- Hermit already exposes an MCP server.
- Hermes has first-class MCP server management.
- MCP preserves the planner/executor separation better than shelling out to a free-form CLI.
- It keeps Hermit as a reusable executor for multiple orchestrators.

### Expected user flow

Possible final UX:

```bash
npm install -g @cafitac/hermit-agent
hermit install --orchestrator hermes
hermes mcp test hermit
```

or if Hermit should not mutate Hermes config by default:

```bash
hermit install --print-hermes-mcp-config
hermes mcp add hermit-channel --command hermit --args mcp-server
hermes mcp test hermit-channel
```

The `mcp add` syntax has been smoke-checked against the local Hermes CLI help/list behavior. A full `hermes mcp test hermit-channel` round trip remains a later smoke because it depends on local Hermes auth/runtime state.

## Implementation slices

### H1 — Document and test config-snippet generation

Objective: provide a safe first surface that prints Hermes setup instructions without mutating `~/.hermes`.

Status:
- Implemented as `hermit install --print-hermes-mcp-config`.
- Uses the stable stdio entry `hermit mcp-server`.
- Does not call the mutating install flow and does not edit real Hermes config.

Files involved:
- `hermit_agent/install_flow.py`
- `hermit_agent/__main__.py`
- new helper: `hermit_agent/orchestrators/hermes.py` or similar
- tests under `tests/`

Behavior:
- Detect `hermes` binary if available.
- Print exact `hermes mcp add` / `hermes mcp test` commands.
- Include the Hermit MCP command and environment needed for gateway URL/API key.
- Do not edit real `~/.hermes/config.yaml` in this slice.

Acceptance:
- Unit test asserts stable command/snippet output.
- Temp HOME/HERMES_HOME test proves no real config mutation.

### H2 — Add doctor checks for Hermes readiness

Objective: `hermit doctor` can say whether Hermes is available and whether Hermit appears registered.

Status:
- Implemented in `hermit doctor` as a non-fatal `Hermes MCP` diagnostic.
- Checks for the `hermes` executable.
- Tries `hermes mcp list --json`, then falls back to `hermes mcp list` for current Hermes versions that do not support `--json`.
- PASSes when `hermit-channel` points at `hermit mcp-server`; otherwise WARNs with setup guidance.

Checks:
- `hermes` executable present.
- `hermes mcp list` returns a `hermit` or configured server name when available.
- gateway URL/API key are present for MCP server use.
- warn, do not fail, if Hermes is not installed.

Acceptance:
- doctor output includes Hermes section when requested or when Hermes is detected.
- tests mock subprocess output and cover missing/registered/broken cases.

### H3 — Optional installer mutation with backup

Objective: allow `hermit install --orchestrator hermes --fix` or similar to register Hermit in Hermes automatically.

Rules:
- Back up any Hermes config file before mutation if direct file writes are used.
- Prefer `hermes mcp add` over hand-editing YAML when possible.
- Print exactly what was changed.
- Keep the operation idempotent.

Acceptance:
- Re-running install does not duplicate MCP entries.
- Existing unrelated Hermes config stays intact.
- Failure produces actionable rollback info.

### H4 — Round-trip smoke

Objective: prove Hermes can invoke Hermit for a small task.

Suggested smoke:
- Isolated temp repo.
- Isolated `HERMES_HOME` when feasible, or explicit user-scope dry-run when model/auth makes isolation impractical.
- `hermes mcp test hermit` passes.
- A tiny Hermit task returns `done` without requiring a real code change.

Acceptance:
- Smoke command and expected output are documented.
- If full isolated Hermes model auth is unavailable, separate MCP wiring smoke from provider/auth smoke.

## Open questions

1. Should Hermit mutate Hermes config by default, or only print commands unless `--fix` is passed?

Recommendation: print-only first, mutation only with explicit `--fix`.

2. Should Hermes use Hermit through MCP or as a subprocess?

Recommendation: MCP first; subprocess only as fallback for non-interactive one-shot tasks.

3. Should Hermit install create Hermes skills/commands?

Recommendation: not initially. Start with MCP registration. Add Hermes skills later if repeated workflows need a nicer user command.

4. How should user approvals flow?

Recommendation: reuse Hermit's existing waiting prompt model, then map it to Hermes MCP/tool interaction semantics. Do not create a Hermes-specific approval protocol until MCP behavior proves insufficient.

## Safety constraints

- Do not assume `~/.hermes` can be modified silently.
- Do not copy Claude hook shapes into Hermes config.
- Do not introduce Anthropic or OpenAI API-key requirements.
- Do not make Hermes support block Claude Code/Codex paths.
