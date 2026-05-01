# PR-06 — Public Readiness Docs and Release Hardening

## Objective

After the behavior is actually verified, update public docs so users can correctly set up and validate Hermit as an executor for Claude Code, Codex, and Hermes Agent.

## Depends on

All previous PRs should be merged:
- PR-01 live smoke truthfulness
- PR-02 Hermes registration/round-trip readiness
- PR-03 task event mapping
- PR-04 Claude/Codex adapter wrappers
- PR-05 runtime boundary decision

## Branch

Suggested branch:

```bash
git checkout main
git pull --ff-only
git checkout -b docs/executor-readiness-public-docs
```

## Files

Likely modify:
- `README.md`
- `docs/cc-setup.md`
- `docs/hermit-variants.md`
- possibly create `docs/hermes-setup.md`
- possibly create/update `docs/codex-setup.md` if a public Codex setup doc is missing
- `docs/known-issues.md`
- `docs/open-source-positioning.md`
- `docs/release-notes-template.md`
- `.dev/refactor/roadmap.md`
- `.dev/refactor/hermes-integration-plan.md`
- `.dev/refactor/orchestrator-adapter-architecture.md`
- `CHANGELOG.md`

## Documentation principle

Do not claim more than verified behavior.

Good wording:
- "Hermes Agent can register Hermit as an MCP server with `hermit install --fix-hermes-mcp`. Verify with `hermit install --test-hermes-mcp`."
- "The MCP server is the canonical runtime boundary; adapter DTOs currently cover setup/health and mapping layers."

Bad wording:
- "Hermes adapter fully supports submit/event/reply/cancel" unless PR-05 actually implemented that.
- "All orchestrators are fully equivalent" if Claude/Codex/Hermes use different interaction mechanisms.

## Test-first / verification plan

Docs PRs still need tests because this repo has hygiene tests.

### Step 1 — Run docs/hygiene tests before edits

```bash
.venv/bin/python -m pytest tests/test_repo_hygiene.py tests/test_cli_defaults.py -q
```

Expected:
- pass

### Step 2 — Update public setup docs

Minimum docs updates:

1. README install section
   - Keep npm-first onboarding.
   - Include Hermes path only if PR-02 proved it:
     ```bash
     hermit install --print-hermes-mcp-config
     hermit install --fix-hermes-mcp
     hermit install --test-hermes-mcp
     ```
   - Explain that `--fix` is explicit mutation and `--print` is read-only.

2. New or updated Hermes setup doc
   - Recommended: `docs/hermes-setup.md`
   - Include:
     - prerequisites
     - print-only setup
     - explicit fix setup
     - doctor/test commands
     - how to interpret failure messages
     - provider/auth boundary: Hermes OAuth config remains Hermes-owned; Hermit setup must not require OpenAI API keys

3. Existing Claude Code setup doc
   - Keep `hermit-channel` details.
   - Keep dev channel caveat if still required.
   - Update known issues if waiting notification retry has proven stable.

4. Codex setup / positioning
   - Make clear whether Codex support is via existing codex-channels/app-server path or generic MCP path.
   - Avoid implying automatic hosted fallback.

### Step 3 — Sync internal roadmap docs

Update:
- `.dev/refactor/roadmap.md`
- `.dev/refactor/hermes-integration-plan.md`
- `.dev/refactor/orchestrator-adapter-architecture.md`

These should match current reality after PR-05.

### Step 4 — Run documentation and full tests

```bash
.venv/bin/python -m pytest tests/test_repo_hygiene.py tests/test_cli_defaults.py tests/test_doctor.py -q
.venv/bin/python -m pytest tests/ -q
```

Expected:
- full suite passes

### Step 5 — Manual package smoke if release follows

If this PR will be released, after merge/release-sync verify:

```bash
npm view @cafitac/hermit-agent@<version> version
python -m venv /tmp/hermit-smoke-venv
/tmp/hermit-smoke-venv/bin/python -m pip install cafitac-hermit-agent==<version>
/tmp/hermit-smoke-venv/bin/hermit --version
```

Adapt paths/version to the repo's existing release flow.

## Acceptance criteria

- Public docs contain a complete, truthful setup path for Hermes Agent.
- Public docs still accurately describe Claude Code and Codex support.
- Internal planning docs no longer contradict README.
- Known issues are updated, not hidden.
- All tests pass.
- Release notes mention executor readiness only at the level actually verified.

## PR description checklist

Include:
- Behavior verified in previous PRs.
- Docs changed.
- Any remaining caveats.
- Test output.
