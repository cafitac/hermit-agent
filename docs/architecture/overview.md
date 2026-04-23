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

## Related documents

- [Channel Notifications (Python MCP)](notifications.md)
- [Security Architecture](security.md)
- [Server Hosting](server-hosting.md)
