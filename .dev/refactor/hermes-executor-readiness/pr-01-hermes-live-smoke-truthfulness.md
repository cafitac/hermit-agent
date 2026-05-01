# PR-01 — Fix Hermes Live-Smoke Truthfulness

## Objective

Make `hermit install --test-hermes-mcp` trustworthy. It must fail when Hermes says `hermit-channel` is missing, even if the Hermes CLI exits with status 0.

## Why this PR comes first

The readiness plan depends on live smoke output. Current behavior produced a false PASS:

```bash
hermes mcp test hermit-channel
# output: ✗ Server 'hermit-channel' not found in config.
# exit: 0

.venv/bin/python -m hermit_agent install --test-hermes-mcp
# output: Hermes MCP live test: passed
```

That makes every later Hermes readiness claim unreliable.

## Branch

Suggested branch:

```bash
git checkout -b fix/hermes-mcp-live-smoke-truthfulness
```

## Files

Likely modify:
- `hermit_agent/install_flow.py`
- `tests/test_install_flow.py` or the existing install-flow test file that covers Hermes install helpers
- `CHANGELOG.md`
- `.dev/refactor/hermes-integration-plan.md`
- `.dev/refactor/hermes-executor-readiness/README.md` if status needs updating after merge

Do not modify:
- `src/`
- `claw-code-main/`
- `hermes-agent/`

## Test-first plan

### Step 1 — Locate existing Hermes install-flow tests

Run:

```bash
search_files equivalent: search for `run_hermes_mcp_connection_test`, `format_hermes_mcp_test_summary`, `test-hermes-mcp`, and `hermes mcp test` in `tests/`.
```

In Hermes tools, use:

```python
search_files(
    "run_hermes_mcp_connection_test|format_hermes_mcp_test_summary|test-hermes-mcp|hermes mcp test",
    path="tests",
    file_glob="*.py",
)
```

### Step 2 — Write RED test for false PASS

Add a test that monkeypatches:
- `shutil.which("hermes")` to return a fake path
- `subprocess.run(...)` to return `returncode=0`, `stdout="✗ Server 'hermit-channel' not found in config."`, `stderr=""`

Expected:

```python
status = run_hermes_mcp_connection_test(cwd="/repo")
assert status.startswith("failed (")
assert "not found" in status
```

Run only the new test:

```bash
.venv/bin/python -m pytest tests/test_install_flow.py::test_hermes_mcp_connection_test_fails_when_server_missing_despite_zero_exit -q
```

Expected before implementation:
- FAIL because current code returns `passed`.

### Step 3 — Add success-shape test

Add a positive test that only returns `passed` when output indicates success.

Use the real Hermes output shape if known from local CLI; otherwise keep the predicate conservative:
- returncode 0
- output does not contain missing/error patterns

Suggested expected behavior:

```python
proc = CompletedProcess(args=[...], returncode=0, stdout="✓ hermit-channel OK", stderr="")
assert run_hermes_mcp_connection_test(cwd="/repo") == "passed"
```

### Step 4 — Implement minimal parser

In `hermit_agent/install_flow.py`, change `run_hermes_mcp_connection_test()` so returncode 0 is not enough.

Add a helper if useful:

```python
def _hermes_mcp_test_output_indicates_failure(output: str) -> bool:
    lowered = output.casefold()
    failure_markers = (
        "not found",
        "no mcp servers configured",
        "server 'hermit-channel' not found",
        "server \"hermit-channel\" not found",
        "failed",
        "error",
    )
    return any(marker in lowered for marker in failure_markers)
```

Then:

```python
combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
if proc.returncode == 0 and not _hermes_mcp_test_output_indicates_failure(combined):
    return "passed"
message = combined.strip() or "Hermes MCP test failed"
return f"failed ({message})"
```

Be careful: do not overfit to the `✗` character only. The English text matters more.

### Step 5 — Run targeted tests

```bash
.venv/bin/python -m pytest tests/test_install_flow.py tests/test_cli_defaults.py tests/test_doctor.py tests/test_hermes_orchestrator_adapter.py -q
```

Expected:
- all pass

### Step 6 — Run actual local smoke before registration

Because local Hermes currently has no MCP servers, this should now fail:

```bash
.venv/bin/python -m hermit_agent install --test-hermes-mcp
```

Expected:
- output starts with `Hermes MCP live test: failed (`
- output recommends `hermit install --fix-hermes-mcp`

### Step 7 — Run full suite

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected:
- full suite passes

## Acceptance criteria

- False PASS is impossible for the observed `Server 'hermit-channel' not found in config.` output.
- Missing Hermes CLI still returns `missing-hermes-cli`.
- Real subprocess failures still return `failed (...)`.
- Adapter `live_smoke()` maps the new failure status to `AdapterHealthStatus.FAIL` without code changes or with updated tests if needed.
- README is not made more optimistic in this PR.
- Internal plan docs are updated if the observed local status changes.

## PR description checklist

Include:
- Problem: Hermes CLI may exit 0 while reporting missing server.
- Fix: inspect output text for missing/error markers before returning `passed`.
- Verification commands and outputs.
- Note: no config mutation; smoke command remains read-only.
