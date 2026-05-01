# Hermit Refactor Program

> Draft planning area for long-running HermitAgent refactor and multi-orchestrator support work.

## Goal

Make Hermit stable as a cheap/mechanical executor while keeping the orchestrator boundary clean enough to support:

- Claude Code
- Codex
- Hermes Agent
- future MCP-capable or subprocess-capable orchestrators

The near-term rule is: stabilize real user paths before large structural refactors.

## Current priority order

1. Keep the test suite green and reproducible.
2. Make install/doctor/smoke flows reliable from a clean user environment.
3. Preserve Claude Code and Codex behavior while extracting shared orchestration boundaries.
4. Add Hermes support as a first-class orchestrator surface, not a special-case hack.
5. Continue internal refactoring only in small, verified slices.

## Documents

- `roadmap.md` — prioritized workstream roadmap and acceptance gates.
- `orchestrator-adapter-architecture.md` — target abstraction for Claude Code, Codex, Hermes, and future orchestrators.
- `hermes-integration-plan.md` — concrete plan for making Hermit usable from Hermes Agent.
- `test-and-release-stabilization.md` — test reproducibility, CI, and release safety tasks.

## Guardrails

- Do not modify `src/`, `claw-code-main/`, or `hermes-agent/`; they are reference repos.
- Keep `.dev/` as AI-managed draft planning. Promote only reviewed, verified user-facing behavior into `docs/`.
- Prefer adapter-neutral names and interfaces. Avoid encoding Claude/Codex assumptions into core runtime code.
- Every refactor slice must end with `.venv/bin/python -m pytest tests/ -q` or a documented narrower gate plus full-suite follow-up.
- If a change touches install, routing, hooks, or credentials, include a clean-HOME smoke test.
