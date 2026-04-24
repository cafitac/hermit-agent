# HermitAgent Architecture Overview

## Component Map

```
┌───────────────────────────────────────────────────────────────┐
│                         User Interface                         │
│   Claude Code (MCP)   │   Telegram   │   HermitAgent TUI/CLI   │
└───────────────┬──────────────┬──────────────────────┬──────────┘
                │              │                      │
                ▼              ▼                      ▼
┌───────────────────────────────────────────────────────────────┐
│                       HermitAgent Core                         │
│                                                               │
│   ┌───────────────┐   ┌──────────────┐   ┌────────────────┐  │
│   │  mcp_server   │   │  AgentLoop   │   │ SkillRegistry  │  │
│   │  (MCP entry   │ → │  (LLM + tool │ ← │ (skill loader) │  │
│   │   + channel   │   │   use loop)  │   └────────────────┘  │
│   │   notifier)   │   └──────┬───────┘                       │
│   └───────┬───────┘          │                               │
│           │            ┌─────▼────────────────────────┐      │
│           │            │ InteractiveSessionRuntime    │      │
│           │            │ (gateway-private TUI chat)   │      │
│           │            └──────────┬───────────────────┘      │
│           │            ┌─────▼──────┐                        │
│           │            │ Tool Layer │                        │
│           │            │  BashTool  │                        │
│           │            │  ReadFile  │                        │
│           │            │  RunTests  │                        │
│           │            │  RunSkill  │                        │
│           │            │  AskUser ──┼──► notify_fn            │
│           │            └────────────┘      │                 │
│           │                                │                 │
│           ▼                                ▼                 │
│  notifications/claude/channel  (_send_channel_notification)  │
└───────────────────────────────────────────────────────────────┘
                │
                ▼
        Claude Code session
        renders as
        <channel source="hermit-channel"> block
```

## Key Components

### hermit_agent/ (Python core)

| Module | Role |
|--------|------|
| `mcp_server.py` | MCP JSON-RPC handler, task lifecycle, channel notifier (`_send_channel_notification`) |
| `loop.py` | AgentLoop — LLM inference + tool-call loop, context compaction |
| `llm_client.py` | LLM client (ollama / z.ai / OpenAI-compatible) |
| `context.py` | Context compression (compaction) |
| `gateway/` | FastAPI relay (rate limiting, failover, SSE to TUI) |
| `gateway/interactive_session_runtime.py` | Gateway-private long-lived interactive session runtime for TUI continuity |
| `tools/` | Tool implementations (Bash, Read, Write, RunTests, RunSkill, AskUser …) |
| `tools/interaction/ask_user.py` | User-question tool that triggers the channel `notify_fn` |

The channel notification path lives inside `mcp_server.py` — there is
no sidecar process, no HTTP webhook, no Bun runtime. See
[notifications.md](notifications.md) for details.

### ~/.claude/commands/*-hermit.md (skill variants)

| File | Role |
|------|------|
| `feature-develop-hermit.md` | Claude interviews; Hermit implements the PR |
| `code-apply-hermit.md` | Claude reads the review; Hermit applies every finding |
| `code-polish-hermit.md` | Claude picks polish targets; Hermit runs lint/test loop |
| `code-push-hermit.md` | Claude writes the PR description; Hermit commits and pushes |

## Data flow — MCP delegation

```
Claude Code
  → run_task(task, cwd, model, background)
  → mcp_server._run_task_thread()
    → AgentLoop.run()
      → LLMClient.chat() ← executor LLM (ollama / z.ai)
      → Tool.execute()
      → AskUserQuestionTool
        → question_queue.put()
        → waiting_prompt snapshot update
        → notify_fn()  ← _send_channel_notification()
        → reply_queue.get()   (blocks)
  ← {status: "waiting", question}
  ← reply_task(task_id, answer)
  → reply_queue.put(answer)
  → AgentLoop resumes
  ← {status: "done", result}
```

## Data flow — TUI interactive continuity

```
Hermit TUI (bridge.py)
  → POST /internal/interactive-sessions
  → gateway-private InteractiveSessionRuntime
    → create one AgentLoop for the current TUI session
    → persist transcript to mode='interactive'/messages.json
  → POST /internal/interactive-sessions/{session_id}/messages
    → same AgentLoop receives the next user turn
    → raw transcript continuity preserved until normal ContextManager compaction
  → GET /internal/interactive-sessions/{session_id}/stream
    → private SSE stream for TUI updates
  ← reply over /internal/interactive-sessions/{session_id}/reply when waiting
```

Important boundary:

- TUI continuity is a **gateway-private interactive runtime** concern.
- TUI startup itself does **not** auto-resume prior sessions; recovery is explicit via `/resume`.
- Public `/tasks` stays task-oriented for MCP and operator flows.
- recap/handoff is recovery UX only; it is not the primary live transcript source when an interactive session is active.

## Channel notification flow

```
AskUserQuestionTool.execute()
  → _notify_channel(task_id, question, options)
  → _fire_channel_notification_sync(content, meta)
  → asyncio.run_coroutine_threadsafe(
        _send_channel_notification(session, content, meta), event_loop)
  → session._write_stream.send(
        SessionMessage(message=JSONRPCMessage(JSONRPCNotification(
            method="notifications/claude/channel",
            params={"content": ..., "meta": ...}))))
  → Claude Code receives the JSON-RPC frame on stdin
  → rendered inline as <channel source="hermit-channel"> block
```

## Ownership summary

- `AgentLoop` and `ContextManager` are the single shared engine and compaction policy.
- `InteractivePrompt` is the canonical in-memory waiting model.
- `waiting_prompt_snapshot()` is the serialized/public waiting snapshot.
- `InteractiveSessionRuntime` owns TUI multi-turn continuity.
- `/tasks` owns public task lifecycle only and must not grow chat/session continuity semantics.

## Related documents

- [Channel Notifications (Python MCP)](notifications.md)
- [Security Architecture](security.md)
- [Server Hosting](server-hosting.md)
