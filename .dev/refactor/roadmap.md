# Refactor Roadmap

## Working thesis

Hermit already has a useful product shape: a cheaper executor lane for premium orchestrators. The next refactor should not chase architectural purity first. It should reduce the risk that real users hit broken install paths, broken interaction channels, or non-reproducible tests.

## Phase 0 — Stabilize current main

### R0.1 Make tests reproducible

Objective: one documented command works locally and in CI.

Tasks:
- Use `.venv/bin/python -m pytest tests/ -q` as the current local verification command.
- Fix or regenerate broken `.venv/bin/pytest` shebang if the repo expects direct pytest entrypoint usage.
- Remove or isolate tests that depend on live `~/.claude` state unless explicitly marked integration.
- Add a short note to the developer docs or README test section once verified.

Status:
- README, CONTRIBUTING, CLAUDE, and HERMIT docs now point developers at `.venv/bin/python -m pytest tests/` rather than the direct `.venv/bin/pytest` entrypoint.
- `tests/test_repo_hygiene.py` guards the documented test command so future docs do not drift back to the stale shebang path.

Acceptance:
- Full suite passes in the repo venv.
- Running plain `pytest` with the wrong Python is no longer the recommended path.
- Test failures do not depend on private user-home skill state.

### R0.2 Fix current regressions

Current known failures from the first stabilization run were:

- `tests/test_codex_channels_mcp_wiring.py::TestCodexChannelsSinkInDefaultComposite::test_notify_graceful_when_enabled_but_server_down`
- `tests/test_skill_triggers.py::test_migrated_skill_has_trigger_keywords[feedback-learning-keywords1]`

Status:
- Done in the current stabilization branch.
- `CodexChannelsInteractiveSink.notify()` clears stale sessions before attempting a new wait-session startup.
- `tests/test_skill_triggers.py` now uses fixture-backed temp Claude skills instead of live `~/.claude` state.
- Latest full verification: `1079 passed, 24 warnings`.

Acceptance:
- Both original regressions pass.
- Full suite returns 0.

## Phase 1 — Install and doctor reliability

### R1.1 Clean-HOME install smoke

Objective: prove a new user can install/configure without editing JSON or understanding topology.

Test shape:
- Set `HOME` to a temp directory.
- Run the install flow in non-interactive mode.
- Assert settings file creation, gateway key creation, idempotent rerun, and doctor output.
- Keep external app registration mocked or fixture-backed.

Status:
- Implemented as a fixture-backed smoke test using an isolated settings path.
- Covers settings creation, generated gateway API key reuse on rerun, and doctor diagnostics for the isolated Hermit directory.

Acceptance:
- `hermit install --yes` or equivalent path is idempotent in a temp HOME.
- `hermit doctor` reports actionable status without crashing.

### R1.2 Align onboarding strategy

Current tension:
- README is npm-first.
- Older `.dev/zero-config-install-ux-plan.md` text is PyPI-first.

Decision to preserve unless product direction changes:
- npm/npx is the primary OSS onboarding surface.
- PyPI remains the Python runtime/package distribution surface.

Acceptance:
- Draft plans agree on npm-first user onboarding.
- Public docs mention one primary path, not competing paths.

## Phase 2 — Adapter boundary extraction

### R2.1 Define orchestrator-neutral contracts

Status: first scaffold implemented in `hermit_agent/orchestrators/contracts.py`; behavior remains on the existing Claude/Codex/Hermes paths until R2.2 extraction slices.

Target surfaces:
- task submission
- progress/status events
- waiting prompt delivery
- reply delivery
- cancellation
- result truncation/summary
- registration/install health checks

Acceptance:
- Claude Code and Codex can both be described as implementations of the same adapter contract.
- Hermes Agent integration has an obvious implementation slot.

### R2.2 Move orchestrator-specific code behind adapters

Status: first Hermes wrapper added as `HermesMcpAdapter`; it maps existing install/doctor/live-smoke helpers to adapter DTOs but does not yet change CLI dispatch or MCP task runtime paths. Prompt mapping helpers now round-trip current runtime `InteractivePrompt` values through the neutral DTOs as another behavior-preserving extraction step.

Likely areas:
- `hermit_agent/mcp_channel.py`
- `hermit_agent/interactive_sinks/*`
- `hermit_agent/codex/*`
- `hermit_agent/mcp/*`
- install/doctor registration helpers

Acceptance:
- Core `AgentLoop` and gateway task lifecycle do not know about Claude/Codex/Hermes-specific delivery details.
- Existing Claude/Codex tests still pass.

## Phase 3 — Hermes support

Objective: Hermit can be used from Hermes Agent as an executor lane.

Deliverables:
- Hermes-facing setup guidance or installer surface.
- Hermes MCP registration or one-shot subprocess bridge, selected by least fragile path.
- Smoke test using isolated `HERMES_HOME` where possible.
- Docs explaining role separation: Hermes = planner/orchestrator, Hermit = mechanical executor.

Acceptance:
- A Hermes user can invoke Hermit for a repo task without manually editing multiple config files.
- The integration does not require OpenAI API keys when Hermes is configured for OpenAI Codex OAuth.
- Existing Claude Code and Codex flows remain green.

## Phase 4 — Internal cleanup after stability

Candidates:
- Continue `loop.py` responsibility extraction.
- Remove or isolate stdin monkeypatch behavior in TUI.
- Reduce broad exception swallowing.
- Tighten type boundaries around session, task, and prompt DTOs.

Acceptance:
- Each cleanup is a small vertical slice with tests.
- No broad rewrite without an immediate product-facing risk reduction.
