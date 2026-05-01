# Test and Release Stabilization Plan

## Why this comes before broad refactoring

Hermit is already positioned publicly as an OSS executor. If the suite is not reproducible, every refactor and integration change becomes ambiguous. The first stabilization target is boring but essential: green tests, deterministic local commands, and install smoke coverage.

## Current local test finding

Observed from repo root:

```bash
pytest tests/ -q
```

failed during collection because the shell picked system Python without project dependencies (`fastapi`, `aiosqlite`).

Observed:

```bash
.venv/bin/pytest tests/ -q
```

failed because `.venv/bin/pytest` has a stale shebang pointing at `/Users/reddit/Project/claude-code/.venv/bin/python`.

Working command:

```bash
.venv/bin/python -m pytest tests/ -q
```

Current result before fixes:

```text
1067 passed, 2 failed, 24 warnings
```

## Immediate fixes

### S1 — Fix codex-channels graceful-down regression

Failing test:

```text
tests/test_codex_channels_mcp_wiring.py::TestCodexChannelsSinkInDefaultComposite::test_notify_graceful_when_enabled_but_server_down
```

Expected behavior:
- if codex-channels is enabled but wait-session startup fails, `notify()` must not raise
- it must not leave `prompt.task_id` in `sessions`

Likely files:
- `hermit_agent/interactive_sinks/codex_channels.py`
- `tests/test_codex_channels_mcp_wiring.py`

Acceptance:
- targeted test passes
- no dangling session remains when startup returns `None` or raises

### S2 — Remove live user-home dependency from skill trigger test

Failing test:

```text
tests/test_skill_triggers.py::test_migrated_skill_has_trigger_keywords[feedback-learning-keywords1]
```

Problem:
- test reads `~/.claude/skills/feedback-learning/SKILL.md`
- result depends on private local user state, not repo state

Preferred fix:
- make the test use a fixture/temp skill directory or a repo-local skill fixture
- keep a separate optional integration test only if checking the real home directory is intentional

Acceptable short-term fix:
- patch the local skill description only if this repo intentionally validates the developer's home skill install
- but this is not preferred for OSS reproducibility

Acceptance:
- full suite does not depend on live `~/.claude` state by default

### S3 — Standardize local test command

Preferred command:

```bash
.venv/bin/python -m pytest tests/ -q
```

Optional cleanup:
- regenerate venv console scripts so `.venv/bin/pytest` works again
- add a small Makefile/script if the project wants a single stable command

Acceptance:
- contributor docs or README test section uses the working command
- CI remains aligned with package install path

## Follow-up smoke coverage

### S4 — Clean-HOME install smoke

Status:
- Implemented with an isolated temp settings path.
- Includes idempotent gateway key reuse and doctor diagnostics for the isolated Hermit directory.

Test should prove:
- settings file is created
- gateway API key is created or reused
- install rerun is idempotent
- doctor reports useful status
- no real user config is mutated

### S5 — Package shape smoke

Test should prove:
- npm package includes `bin` and `dist`
- packaged command starts far enough to show version/help without needing repo files
- managed Python runtime version sync still points at the published version

### S6 — Orchestrator smoke matrix

Status:
- Codex channel-unavailable behavior is regression-tested.
- Hermes MCP config snippet generation is regression-tested.
- Hermes MCP doctor detection covers missing CLI, registered JSON output, current text-only `hermes mcp list` output, and subprocess errors.

Minimum matrix:
- Claude Code MCP registration dry-run/check
- Codex channel unavailable graceful behavior
- Hermes MCP config snippet generation

## Done criteria before next large refactor

- Full local suite green.
- Known user-home-dependent tests either fixture-backed or marked integration.
- Clean-HOME install smoke exists.
- TUI manual verification doc is updated with a pass/fail result.
