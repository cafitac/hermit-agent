# Orchestrator Adapter Architecture

## Problem

Hermit currently supports Claude Code and Codex, but several integration details are spread across MCP server code, channel notification code, codex-channels code, install flow, and tests. Adding Hermes Agent should not mean adding a third set of special cases in the core loop.

## Target model

Hermit core should expose an executor task protocol. Orchestrators should be adapters around that protocol.

```
Orchestrator
  -> adapter submit_task()
  -> Hermit gateway/task runtime
  -> AgentLoop + tools
  -> adapter emit_event()/wait_for_reply()
  -> Orchestrator
```

## Adapter responsibilities

Each orchestrator adapter should own:

1. Registration/setup
   - how the orchestrator discovers Hermit
   - how local config is written or printed
   - how credentials and local endpoints are validated

2. Task submission
   - task prompt
   - cwd
   - model/routing hints
   - background vs foreground behavior

3. Event delivery
   - running/progress updates
   - waiting prompts
   - permission prompts
   - done/error notifications

4. Reply delivery
   - user answers to Hermit waiting prompts
   - approval/denial payloads
   - cancellation

5. Result shaping
   - result truncation
   - machine-readable status
   - human-readable summary

6. Smoke checks
   - clean setup validation
   - one waiting prompt round trip
   - one done result round trip

## Existing adapters

### Claude Code

Likely implementation shape:
- MCP server registration through Claude config.
- `run_task`, `reply_task`, `check_task`, `cancel_task` tools.
- `notifications/claude/channel` for visible channel events.

Known risk:
- waiting notification loss or stale channel state can leave tasks waiting.
- tests must not rely on live user `~/.claude` unless marked integration.

### Codex

Likely implementation shape:
- Codex app-server / codex-channels runtime for async interaction.
- codex runner and interactive sink bridge.
- explicit opt-in routing for hosted Codex executor models.

Known risk:
- channel server down or stale session must not leave dangling wait sessions.
- OAuth/provider policy belongs to the orchestrator's config and must not be silently bypassed.

### Hermes Agent

Preferred implementation options, in order of likely durability:

1. MCP server integration
   - Hermit exposes an MCP server.
   - Hermes registers it via `hermes mcp add` or an installer-generated config snippet.
   - Hermes invokes Hermit as a tool for delegated execution.

2. One-shot subprocess integration
   - Hermes calls a stable Hermit CLI command for bounded tasks.
   - Useful as a fallback or early smoke path.
   - Less interactive unless paired with a reply bridge.

3. Native Hermes plugin integration
   - Only if MCP/subprocess is insufficient.
   - Higher coupling to Hermes internals, so defer until proven necessary.

## Contract sketch

Implemented scaffold: `hermit_agent/orchestrators/contracts.py` now defines the first orchestrator-neutral DTO/protocol layer. Existing Claude/Codex/Hermes flows have not moved behind the protocol yet; this keeps the first slice behavior-free and gives later extraction work a tested shared vocabulary.

Use this as the design target for the scaffold and later adapter extraction:

```python
class OrchestratorAdapter:
    name: str

    def install_or_print_instructions(self, *, cwd: str, fix: bool) -> AdapterInstallResult: ...
    def health(self, *, cwd: str) -> AdapterHealth: ...
    def submit_task(self, request: TaskRequest) -> TaskHandle: ...
    def emit_event(self, task_id: str, event: TaskEvent) -> None: ...
    def wait_for_reply(self, task_id: str, prompt: InteractivePrompt) -> PromptReply | None: ...
    def cancel(self, task_id: str) -> None: ...
```

DTOs should stay orchestrator-neutral:
- `TaskRequest`
- `TaskHandle`
- `TaskEvent`
- `InteractivePrompt`
- `PromptReply`
- `AdapterHealth`
- `AdapterInstallResult`

Current test anchor:
- `tests/test_orchestrator_contracts.py` verifies immutable DTO shape, stable status/event enum values, and the structural lifecycle shape of `OrchestratorAdapter`.
- `tests/test_hermes_orchestrator_adapter.py` verifies `HermesMcpAdapter` maps existing Hermes install, live-smoke, and doctor helpers into `AdapterInstallResult` / `AdapterHealth` without mutating behavior.

Next extraction candidates:
- map existing interactive prompt/session objects into the neutral `InteractivePrompt` / `PromptReply` pair without changing runtime behavior
- start equivalent Claude/Codex install and health wrappers after the Hermes wrapper shape proves stable

## Non-goals

- Do not make Hermes, Claude Code, or Codex share credentials.
- Do not assume Hermes config controls Hermit config or vice versa.
- Do not add provider fallback behavior that surprises users about billing.
- Do not modify reference repos (`src/`, `claw-code-main/`, `hermes-agent/`).

## Test strategy

Unit tests:
- adapter health parsing
- config snippet generation
- task event mapping
- reply payload mapping

Integration-ish tests with temp HOME/HERMES_HOME:
- install output does not mutate real user config
- generated Hermes config snippet is stable
- MCP registration command/instructions are correct

Manual smoke:
- Hermes running with OpenAI Codex OAuth can delegate a small repo task to Hermit without OpenAI API key use.
- Claude Code and Codex existing flows still pass after adapter extraction.
