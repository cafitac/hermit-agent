# PR-03 — Map Gateway/MCP Task Lifecycle Into Neutral TaskEvent DTOs

## Objective

Add pure mapping helpers that convert existing gateway/MCP/SSE task lifecycle payloads into `hermit_agent.orchestrators.contracts.TaskEvent` values without changing runtime delivery behavior.

## Depends on

PR-01 should be merged. PR-02 is recommended but not strictly required if this PR stays pure and does not mutate Hermes runtime behavior.

## Branch

Suggested branch:

```bash
git checkout main
git pull --ff-only
git checkout -b refactor/task-event-dto-mapping
```

## Files

Likely create/modify:
- Create: `hermit_agent/orchestrators/events.py`
- Modify: `hermit_agent/orchestrators/__init__.py`
- Test: `tests/test_orchestrator_event_mapping.py`
- Reference only unless needed: `hermit_agent/channels_core/event_adapters.py`
- Reference only unless needed: `hermit_agent/mcp_sse_bridge.py`
- Reference only unless needed: `hermit_agent/mcp_actions.py`
- Docs: `.dev/refactor/orchestrator-adapter-architecture.md`
- Docs: `.dev/refactor/roadmap.md`
- Docs: `CHANGELOG.md`

## Current relevant code

Existing neutral DTO:
- `TaskEvent(task_id, kind, message="", payload={})`
- `TaskEventKind`: `submitted`, `progress`, `waiting`, `running`, `done`, `error`, `cancelled`

Existing runtime path:
- `mcp_server._SSEBridge._handle_sse_event()` receives SSE events.
- `channels_core.event_adapters.channel_action_from_sse_event()` maps SSE events to channel actions.
- `mcp_actions.dispatch_channel_action()` sends channel notifications.

## Design constraint

This PR must not rewire delivery. It should only add tested mapping helpers so later PRs can switch delivery behind adapters safely.

## Test-first plan

### Step 1 — Write tests for known event shapes

Create `tests/test_orchestrator_event_mapping.py`.

Cover at least:
- submitted/running style event maps to `TaskEventKind.RUNNING` or `SUBMITTED`
- progress message maps to `TaskEventKind.PROGRESS`
- waiting/question event maps to `TaskEventKind.WAITING` and preserves question/options/tool metadata
- done event maps to `TaskEventKind.DONE` and preserves summary/result metadata
- error event maps to `TaskEventKind.ERROR`
- cancel event maps to `TaskEventKind.CANCELLED` if an existing payload shape exists
- unknown event maps conservatively to `PROGRESS` or returns `None`; choose one and document it

Use actual fixture shapes from existing SSE/action tests where possible.

### Step 2 — Observe RED

Run:

```bash
.venv/bin/python -m pytest tests/test_orchestrator_event_mapping.py -q
```

Expected:
- FAIL because `hermit_agent.orchestrators.events` does not exist.

### Step 3 — Implement pure helpers

Suggested API:

```python
def sse_event_to_task_event(task_id: str, event: dict[str, object]) -> TaskEvent | None: ...

def channel_action_to_task_event(task_id: str, action: object) -> TaskEvent | None: ...
```

Keep payload copying defensive:
- do not mutate input dicts
- preserve unknown keys under `payload`
- convert non-string messages safely with `str(...)`

### Step 4 — Export helper if public surface is intended

Modify `hermit_agent/orchestrators/__init__.py` if tests or downstream code should import the helper from the package.

### Step 5 — Targeted regression

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_orchestrator_event_mapping.py \
  tests/test_orchestrator_contracts.py \
  tests/test_orchestrator_prompt_mapping.py \
  tests/test_mcp_notification_wire.py \
  tests/test_mcp_channel_buffering.py \
  -q
```

Expected:
- all pass

### Step 6 — Full regression

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected:
- full suite passes

## Acceptance criteria

- Existing runtime delivery behavior is unchanged.
- Current event/prompt metadata can be represented in neutral DTOs.
- Mapping helpers are tested and defensive against unknown payloads.
- Architecture docs state this is a mapping-only slice.

## PR description checklist

Include:
- This is behavior-preserving.
- No CLI/MCP runtime delivery path was changed.
- List event shapes covered.
- Include targeted and full test output.
