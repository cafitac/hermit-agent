# PR-04 — Add Claude and Codex Adapter Wrappers for Install/Health

## Objective

Bring Claude Code and Codex setup/health surfaces to the same neutral adapter DTO layer as `HermesMcpAdapter`, without changing existing CLI/runtime behavior.

## Depends on

PR-03 is recommended so prompt/event mapping vocabulary is already stable, but this PR can proceed independently if it only wraps install/health helpers.

## Branch

Suggested branch:

```bash
git checkout main
git pull --ff-only
git checkout -b refactor/claude-codex-adapter-wrappers
```

## Files

Likely create/modify:
- Create: `hermit_agent/orchestrators/claude.py`
- Create: `hermit_agent/orchestrators/codex.py`
- Modify: `hermit_agent/orchestrators/__init__.py`
- Test: `tests/test_claude_orchestrator_adapter.py`
- Test: `tests/test_codex_orchestrator_adapter.py`
- Existing helpers to inspect:
  - `hermit_agent/install_flow.py`
  - `hermit_agent/doctor.py`
  - `hermit_agent/codex_channels_*` modules
  - `hermit_agent/codex_app_server_bridge.py`
- Docs:
  - `.dev/refactor/orchestrator-adapter-architecture.md`
  - `.dev/refactor/roadmap.md`
  - `CHANGELOG.md`

## Design constraint

This PR is wrapper-only. Do not rewrite CLI dispatch, MCP server runtime, codex-channels runtime, or Claude channel notification behavior.

## Expected adapter shape

Mirroring `HermesMcpAdapter`:

```python
class ClaudeCodeMcpAdapter:
    name = "claude-code"
    def install_or_print_instructions(...): ...
    def health(...): ...
    def submit_task(...): raise NotImplementedError(...)
    def emit_event(...): raise NotImplementedError(...)
    def wait_for_reply(...): raise NotImplementedError(...)
    def cancel(...): raise NotImplementedError(...)
```

```python
class CodexAdapter:
    name = "codex"
    def install_or_print_instructions(...): ...
    def health(...): ...
    def submit_task(...): raise NotImplementedError(...)
    def emit_event(...): raise NotImplementedError(...)
    def wait_for_reply(...): raise NotImplementedError(...)
    def cancel(...): raise NotImplementedError(...)
```

Use clearer class names if the existing code implies more specific surfaces.

## Test-first plan

### Step 1 — Inspect existing setup/doctor helpers

Find existing functions for:
- Claude MCP registration inspection/repair
- Codex channel install/status/health
- doctor checks that already report Claude/Codex readiness

Use:

```python
search_files("Claude|claude|Codex|codex|mcp registration|register_claude|codex-channels", path="hermit_agent", file_glob="*.py")
```

### Step 2 — Write Claude adapter tests

Cover:
- print-only path returns `AdapterInstallStatus.PRINTED` and does not mutate config
- explicit fix path maps existing helper statuses to `REGISTERED`, `UNCHANGED`, `FAILED`
- health maps doctor status to `AdapterHealthStatus`
- lifecycle methods raise explicit `NotImplementedError`

### Step 3 — Write Codex adapter tests

Cover:
- status/health wrappers map existing codex-channel diagnostics into `AdapterHealth`
- install/fix wrapper delegates to existing Codex setup helper if such helper exists
- if there is no safe install helper, return `SKIPPED` with actionable details rather than inventing behavior
- lifecycle methods raise explicit `NotImplementedError`

### Step 4 — Observe RED

```bash
.venv/bin/python -m pytest tests/test_claude_orchestrator_adapter.py tests/test_codex_orchestrator_adapter.py -q
```

Expected:
- FAIL because modules/classes do not exist.

### Step 5 — Implement thin wrappers

Important:
- delegate to existing helpers
- do not duplicate registration logic
- do not mutate config from print-only methods
- do not collapse credentials across orchestrators

### Step 6 — Targeted regression

```bash
.venv/bin/python -m pytest \
  tests/test_claude_orchestrator_adapter.py \
  tests/test_codex_orchestrator_adapter.py \
  tests/test_hermes_orchestrator_adapter.py \
  tests/test_orchestrator_contracts.py \
  tests/test_codex_channels_adapter.py \
  tests/test_codex_channels_mcp_wiring.py \
  tests/test_mcp_server.py \
  -q
```

Expected:
- all pass

### Step 7 — Full regression

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected:
- full suite passes

## Acceptance criteria

- Claude, Codex, and Hermes can all be described through setup/health adapter DTOs.
- Runtime behavior remains unchanged.
- Unsupported lifecycle methods fail explicitly.
- Docs list all three wrappers and what they do not yet own.

## PR description checklist

Include:
- Wrapper-only scope.
- No runtime path changes.
- Status mapping table for Claude and Codex.
- Targeted and full test output.
