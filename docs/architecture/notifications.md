# Channel Notifications (Python MCP)

HermitAgent surfaces live task progress inside a Claude Code session as
`<channel source="hermit-channel">` frames. This document describes how
that path works now that the mechanism lives entirely inside the Python
MCP server and its extracted channel-runtime helpers.

## Overview

```
┌──────────────────────┐
│    Claude Code       │
│  (MCP host, stdio)   │
└──────────▲───────────┘
           │ JSON-RPC 2.0 over stdio
           │
┌──────────┴───────────┐
│  hermit MCP server   │  (Python, hermit_agent/mcp_server.py)
│  server name:        │
│     "hermit-channel" │
│                      │
│  • tools: run_task,  │
│    reply_task,       │
│    check_task,       │
│    register_task,    │
│    cancel_task       │
│                      │
│  • custom notif:     │
│    notifications/    │
│      claude/channel  │
└──────────┬───────────┘
           │ HTTP REST / SSE
           ▼
┌──────────────────────┐
│   AI Gateway         │
│   (FastAPI, :8765)   │
└──────────────────────┘
```

A single Python MCP server handles both role halves, but the runtime is
now split internally:

- **Request/response tools** (`run_task`, `reply_task`, …) for Claude
  Code to delegate work.
- **Server-push notifications** using the custom JSON-RPC method
  `notifications/claude/channel`, which Claude Code renders as a
  `<channel source="hermit-channel">` block inside the session.
- **`hermit_agent/mcp_channel.py`** owns active-session tracking,
  buffering, and raw channel notification delivery.
- **`hermit_agent/mcp_sse_bridge.py`** owns Gateway SSE consumption and
  maps Gateway events into channel actions.

The earlier Bun-based sidecar has been removed; both responsibilities
live inline in the Python process.

## How the notification gets on the wire

Python's `mcp` SDK (>= 1.27) exposes typed `send_notification()` /
`send_progress_notification()` etc. on `ServerSession`, but
`ServerNotification` is a **closed** discriminated union — it does not
accept custom method names like `notifications/claude/channel`. The
Bun SDK works around this with `as any`; Python works around it by
writing a raw `JSONRPCNotification` straight to the session's
outgoing stream:

```python
from mcp.types import JSONRPCNotification, JSONRPCMessage
from mcp.shared.message import SessionMessage


async def _send_channel_notification(session, content: str, meta: dict) -> None:
    notif = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/claude/channel",
        params={"content": content, "meta": meta},
    )
    await session._write_stream.send(SessionMessage(message=JSONRPCMessage(notif)))
```

`_write_stream` is a private attribute by name (underscore prefix).
Stability across SDK releases is not contractually guaranteed, so the
repo takes two precautions:

1. `pyproject.toml` pins an upper bound: `mcp>=1.27,<2.0`.
2. `tests/test_mcp_notification_wire.py` runs the notification through
   a subprocess and asserts on the wire format (`content` and the full
   `meta` dict, including `step`) on every test run.

If the SDK changes `_write_stream`, step 2 fails loudly before users
do.

## Buffered delivery

Early channel events can arrive before the MCP session loop has been
attached for the current stdio process. Instead of dropping those
events, `hermit_agent/mcp_channel.py` now buffers them and flushes them
once `_set_active_session(...)` is called from the tool handlers. That
keeps early `waiting` / `running` / `error` notifications more reliable
for Claude Code channel rendering.

## `experimental_capabilities`

Claude Code only forwards `notifications/claude/channel` to its
renderer when the MCP server advertises the matching experimental
capability during `initialize`. `FastMCP` calls
`create_initialization_options()` without passing that argument, so
the server lambda-wraps it once at startup:

```python
original_create_init = mcp_app._mcp_server.create_initialization_options

def _create_init_with_channel_caps(**kw):
    kw.setdefault(
        "experimental_capabilities",
        {"claude/channel": {}, "claude/channel/permission": {}},
    )
    return original_create_init(**kw)

mcp_app._mcp_server.create_initialization_options = _create_init_with_channel_caps
```

## Payload shape

Every channel notification is a plain JSON-RPC frame:

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/claude/channel",
  "params": {
    "content": "task running",
    "meta": {
      "task_id": "f46e33d9…",
      "kind": "running"
    }
  }
}
```

`content` is free-form HTML-ish text that Claude Code displays inline.
`meta` is opaque to Claude Code but used by HermitAgent's own log / UI
paths. The runtime payload uses `kind` (not `type`) because `type` was
treated as reserved in earlier channel experiments. The known `kind`
values are `waiting`, `running`, `done`, `reply`, and `error`.

`tests/test_mcp_notification_wire.py` still covers a broader raw JSON-RPC
shape using extra metadata keys (`type`, `step`, `source`) via the probe
script, because the lower-level notification path must remain tolerant of
custom metadata even though HermitAgent's runtime now emits the narrower
`kind`-based shape above.

## Session routing

Each Claude Code session spawns its own stdio subprocess, and each
subprocess owns exactly one `ServerSession`. Notifications therefore
route to the correct CC session automatically — there is no port
registry, no shared database, no `~/.hermit/channel-registry.json`.

The `register_task` tool is kept for backward compatibility with the
bundled `-hermit` skills (which call `mcp__hermit-channel__register_task`
after `run_task`). Internally it is a no-op that stashes the active
session reference so later `_notify_*` callbacks in the agent loop
can emit notifications without re-plumbing the MCP context.

## Setup

See [docs/cc-setup.md](../cc-setup.md). The short version:

1. Register one MCP server under the name `hermit-channel` in
   `~/.claude.json`, pointing at `./bin/mcp-server.sh`.
2. Start Claude Code with
   `--dangerously-load-development-channels server:hermit-channel`
   so CC loads the `claude/channel` capability.
   The MCP launcher auto-starts the local gateway when needed and skips the
   start when the gateway is already healthy.
