# PR-02 — Prove Hermes MCP Registration and Round-Trip Readiness

## Objective

Make Hermes MCP setup verifiably ready after explicit user-requested registration. This PR should establish that `--fix-hermes-mcp`, `hermes mcp list`, `hermit doctor`, and `--test-hermes-mcp` agree with each other.

## Depends on

PR-01 must be merged first. Otherwise `--test-hermes-mcp` can produce false PASS and this PR cannot prove readiness.

## Branch

Suggested branch:

```bash
git checkout main
git pull --ff-only
git checkout -b feat/hermes-mcp-registration-roundtrip
```

## Files

Likely modify:
- `hermit_agent/install_flow.py`
- `hermit_agent/doctor.py`
- `tests/test_install_flow.py`
- `tests/test_doctor.py`
- `README.md` only if behavior is verified and wording stays accurate
- `.dev/refactor/hermes-integration-plan.md`
- `.dev/refactor/hermes-executor-readiness/README.md`

## Core question

Can a Hermes user do this without manual config edits?

```bash
hermit install --fix-hermes-mcp
hermes mcp list
hermit doctor
hermit install --test-hermes-mcp
```

Expected final shape:
- registration is explicit, not default
- registration is idempotent
- doctor PASS only when list output contains `hermit-channel`, `hermit`, and `mcp-server`
- test PASS only when live MCP probe actually succeeds

## Test-first plan

### Step 1 — Add idempotency tests around `ensure_hermes_mcp_registered()`

Cover:
1. `hermes` missing → `missing-hermes-cli`
2. `hermes mcp list` already contains expected entry → `unchanged`
3. list missing expected entry, add succeeds → `registered`
4. add fails → `failed (...)`

These may already partially exist; extend rather than duplicate.

### Step 2 — Add doctor/list consistency tests

`doctor._check_hermes_mcp(cwd)` should:
- WARN when Hermes missing
- WARN when list says no servers
- WARN when `hermit-channel` exists but command/args are not `hermit mcp-server`
- PASS when expected entry is present

Include both JSON and text list output paths if current doctor supports both.

### Step 3 — Verify actual local pre-registration behavior

Before mutation, run:

```bash
hermes mcp list
.venv/bin/python -m hermit_agent doctor
.venv/bin/python -m hermit_agent install --test-hermes-mcp
```

Expected before fix registration:
- list says no MCP servers or does not contain `hermit-channel`
- doctor WARN
- test failed, not passed

### Step 4 — Explicitly register Hermes MCP

This is a user-config mutation. Only do it when this PR is being actively executed and the user has asked to proceed with implementation, not during planning.

Run:

```bash
.venv/bin/python -m hermit_agent install --fix-hermes-mcp
```

Expected:
- `Hermes MCP registration: registered` or `unchanged`
- next-step guidance mentions `--test-hermes-mcp`

Then:

```bash
hermes mcp list
```

Expected:
- output includes `hermit-channel`
- output includes `hermit`
- output includes `mcp-server`

### Step 5 — Verify doctor and smoke after registration

Run:

```bash
.venv/bin/python -m hermit_agent doctor
.venv/bin/python -m hermit_agent install --test-hermes-mcp
```

Expected:
- doctor `Hermes MCP` PASS
- smoke `passed`

If Hermes `mcp test` only validates server startup and not an actual tool call, document that limitation and add a later PR task for tiny task invocation.

### Step 6 — Tiny task round-trip decision

Try to identify whether Hermes CLI exposes an MCP tool call test beyond `mcp test`.

Use only read-only discovery first:

```bash
hermes mcp --help
hermes mcp test --help
```

If Hermes can invoke a tool directly, add a smoke for a tiny no-op Hermit task.

If Hermes cannot invoke tools directly from CLI, document the manual Hermes session smoke:
- start a Hermes Agent session after registration
- verify `hermit-channel` tools are visible
- invoke `run_task` with `task="say hello and exit"`, `background=false`, `cwd=<temp repo>`
- verify `done`

Do not fake this in tests.

### Step 7 — Full regression

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected:
- full suite passes

## Acceptance criteria

- Hermes registration command is idempotent.
- Pre-registration smoke fails truthfully.
- Post-registration smoke passes only when server exists and starts.
- `hermit doctor` agrees with actual `hermes mcp list` state.
- Docs distinguish MCP wiring smoke from full model/provider/auth smoke.
- No OpenAI API key or Anthropic key requirement is introduced.

## PR description checklist

Include:
- Exact pre-registration outputs.
- Exact registration output.
- Exact post-registration `hermes mcp list`, `doctor`, and `--test-hermes-mcp` outputs.
- Whether a tiny task invocation was possible from CLI or remained manual.
