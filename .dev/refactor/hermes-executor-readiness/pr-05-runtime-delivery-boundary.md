# PR-05 — Decide and Implement the Runtime Delivery Boundary

## Objective

Resolve the biggest architecture ambiguity: should `OrchestratorAdapter` own runtime task lifecycle (`submit_task`, `emit_event`, `wait_for_reply`, `cancel`) for Claude/Codex/Hermes, or should the existing MCP server remain the canonical runtime boundary while adapters own setup/doctor/smoke only?

This PR must make that decision explicit in code and docs.

## Depends on

Recommended prerequisites:
- PR-01 merged
- PR-02 merged
- PR-03 merged
- PR-04 merged

Without the prior mapping/wrapper PRs, this PR is too broad.

## Branch

Suggested branch:

```bash
git checkout main
git pull --ff-only
git checkout -b refactor/runtime-delivery-boundary
```

## Decision options

### Option A — Full runtime adapters

Implement lifecycle methods for each adapter:
- `submit_task() -> TaskHandle`
- `emit_event(task_id, event) -> None`
- `wait_for_reply(task_id, prompt) -> PromptReply | None`
- `cancel(task_id) -> None`

Pros:
- matches target architecture in `.dev/refactor/orchestrator-adapter-architecture.md`
- core task lifecycle can become orchestrator-neutral
- future orchestrators are cleaner

Cons:
- high risk
- may duplicate MCP server/gateway proxy logic
- channel semantics differ between Claude, Codex, and Hermes

### Option B — MCP server is canonical runtime; adapters own setup/health/smoke

Keep lifecycle methods explicitly unsupported or move them to a narrower protocol. Rename/reframe contract if necessary:
- `OrchestratorSetupAdapter` or split protocols
- `RuntimeOrchestratorAdapter` reserved for future

Pros:
- honest representation of current working system
- lower risk
- avoids broad rewrite
- still supports Hermes through MCP

Cons:
- target architecture becomes less ambitious
- later runtime extraction remains future work

## Recommended approach

Choose Option B unless there is a clear product-facing bug that requires Option A now.

Reason: The user wants functional readiness for Claude Code, Codex, and Hermes as executor orchestrators. A truthful, tested MCP runtime boundary is more valuable than a broad adapter rewrite. Full runtime adapters can remain a later Phase 4+ refactor.

## Files

Option B likely modify:
- `hermit_agent/orchestrators/contracts.py`
- `hermit_agent/orchestrators/hermes.py`
- `hermit_agent/orchestrators/claude.py` if created in PR-04
- `hermit_agent/orchestrators/codex.py` if created in PR-04
- `tests/test_orchestrator_contracts.py`
- adapter wrapper tests
- `.dev/refactor/orchestrator-adapter-architecture.md`
- `.dev/refactor/roadmap.md`
- `CHANGELOG.md`

Option A likely modify many more runtime files:
- `hermit_agent/mcp_server.py`
- `hermit_agent/mcp_tool_handlers.py`
- `hermit_agent/mcp_task_proxy.py`
- `hermit_agent/mcp_sse_bridge.py`
- `hermit_agent/mcp_actions.py`
- `hermit_agent/mcp_channel.py`
- `hermit_agent/interactive_sinks/*`
- Codex runtime files

Avoid Option A unless explicitly approved for a larger refactor.

## Option B implementation plan

### Step 1 — Split or clarify protocols

In `contracts.py`, consider splitting:

```python
class OrchestratorSetupAdapter(Protocol):
    name: str
    def install_or_print_instructions(...): ...
    def health(...): ...

class OrchestratorRuntimeAdapter(OrchestratorSetupAdapter, Protocol):
    def submit_task(...): ...
    def emit_event(...): ...
    def wait_for_reply(...): ...
    def cancel(...): ...
```

Keep old `OrchestratorAdapter` as alias/subclass only if needed for compatibility.

### Step 2 — Update tests

Adjust contract tests to assert:
- setup adapter shape exists and is used by Hermes/Claude/Codex wrappers
- runtime adapter shape exists as a future protocol if retained
- setup wrappers are not required to implement runtime lifecycle

### Step 3 — Update adapter classes

For setup-only wrappers, remove lifecycle methods or keep explicit `NotImplementedError` depending on chosen protocol compatibility.

If removed, update tests accordingly.

### Step 4 — Update docs honestly

`.dev/refactor/orchestrator-adapter-architecture.md` must say:
- MCP server is currently the canonical task runtime for all orchestrators.
- Adapters currently own setup/health/smoke DTO surfaces.
- Runtime adapter extraction is future work and not required for Hermes readiness unless a concrete bug demands it.

`.dev/refactor/roadmap.md` must update R2/R3 statuses.

### Step 5 — Targeted tests

```bash
.venv/bin/python -m pytest \
  tests/test_orchestrator_contracts.py \
  tests/test_hermes_orchestrator_adapter.py \
  tests/test_orchestrator_prompt_mapping.py \
  tests/test_orchestrator_event_mapping.py \
  tests/test_mcp_tool_handlers.py \
  tests/test_mcp_server.py \
  -q
```

Add Claude/Codex adapter tests if PR-04 created them.

### Step 6 — Full regression

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected:
- full suite passes

## Acceptance criteria

- The code no longer implies Hermes runtime lifecycle is ready through `HermesMcpAdapter` if it is not.
- The docs and tests agree on the canonical runtime boundary.
- Hermes executor readiness is defined around the MCP server path, not unimplemented adapter methods.
- Claude Code and Codex existing flows remain green.

## PR description checklist

Include:
- Chosen option and why.
- What changed in contracts.
- What remains future work.
- Targeted and full test output.
