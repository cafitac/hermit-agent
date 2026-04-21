"""HermitAgent Bridge — Gateway HTTP client mode.

Communicates with React+Ink UI via JSON protocol. All execution routes through the gateway (localhost:8765).

Environment variables:
  HERMIT_GATEWAY_URL     Gateway URL (default: http://localhost:8765)
  HERMIT_GATEWAY_API_KEY Gateway API key (required)

Protocol:
  UI → Python (stdin):
    {"type":"user_input","text":"..."}
    {"type":"interrupt"}
    {"type":"quit"}
    {"type":"permission_response","choice":"yes"|"no"|"always"}
    {"type":"permission_mode","mode":"yolo"}

  Python → UI (stdout):
    {"type":"ready","model":"...","session_id":"gateway",...}
    {"type":"streaming","token":"A"}
    {"type":"stream_end"}
    {"type":"text","content":"..."}
    {"type":"tool_use","name":"bash","detail":"ls -la","ts":...}
    {"type":"tool_result","content":"...","is_error":false,"ts":...}
    {"type":"status","turns":5,"ctx_pct":42,...}
    {"type":"done"}
    {"type":"error","message":"..."}
    {"type":"permission_ask","tool":"bash","summary":"...","options":[...]}"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)

_real_stdout = sys.__stdout__

try:
    from .loop import VERSION
except Exception:
    VERSION = "0.0.0"

from .channels_core.event_adapters import bridge_messages_from_sse_event
from .bridge_commands import build_bridge_commands
from .bridge_runtime import BridgeRuntime


def _send(msg: dict) -> None:
    """Send JSON message to UI. Always uses the original stdout."""
    _real_stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    _real_stdout.flush()


def _dispatch_sse_to_tui(event: dict) -> None:
    """Convert SSE event dict → TUI JSON protocol and send."""
    for msg in bridge_messages_from_sse_event(event, now=time.time):
        _send(msg)
    # done/cancelled/error terminators are handled in the _run_gateway_mode main loop


def _run_gateway_mode(args: argparse.Namespace) -> None:
    """Main loop for Gateway HTTP client mode."""
    from .bridge_client import GatewayClient
    from .config import load_settings, get_primary_model

    client = GatewayClient(base_url=args.gateway_url, api_key=args.gateway_api_key)
    display_model = args.model
    if display_model == "__auto__":
        cfg = load_settings(cwd=args.cwd)
        display_model = get_primary_model(cfg, available_only=True) or get_primary_model(cfg) or "__auto__"

    if not client.check_gateway():
        _send({"type": "error", "message": f"Gateway connection failed: {args.gateway_url}"})
        _send({"type": "done"})
        return

    commands = build_bridge_commands()

    _send({
        "type": "ready",
        "model": display_model,
        "session_id": "gateway",
        "cwd": args.cwd,
        "permission": "accept_edits",
        "version": VERSION,
        "commands": commands,
    })

    msg_queue: queue.Queue = queue.Queue()
    runtime = BridgeRuntime(msg_queue)

    # ── TUI session logging ──
    import uuid as _uuid
    from .session_store import SessionStore
    from .session_logger import SessionLogger as _SessionLogger
    session_id = _uuid.uuid4().hex[:12]
    session_dir = SessionStore().create_session(mode='tui', session_id=session_id, cwd=args.cwd)
    session_logger = _SessionLogger(session_dir=session_dir)

    # ── Auto-recap on stale TUI startup ──
    try:
        from .skills.recap import should_auto_recap, generate_recap
        if should_auto_recap(args.cwd):
            recap_text = generate_recap(args.cwd)
            if recap_text and recap_text != 'No recent session found.':
                _send({"type": "text", "content": "[Auto-recap of last session]\n" + recap_text})
    except Exception:
        pass


    def _stdin_reader() -> None:
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg_queue.put(json.loads(raw_line))
            except json.JSONDecodeError:
                continue

    def _sse_reader(task_id: str) -> None:
        for event in client.stream_events(task_id, runtime.sse_shutdown):
            runtime.msg_queue.put({"_source": "sse", **event})
            if event.get("type") in ("done", "error", "cancelled"):
                break

    stdin_thread = threading.Thread(target=_stdin_reader, daemon=True)
    stdin_thread.start()

    while True:
        try:
            msg = msg_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # Handle SSE events
        if msg.get("_source") == "sse":
            t = msg.get("type")
            if t == "done":
                # done SSE result field → TUI text event (final response)
                result_text = (msg.get("result") or "").strip()
                session_logger.on_send(msg)  # capture final assistant response
                if result_text:
                    _send({"type": "text", "content": result_text})
                _send({"type": "stream_end"})
                runtime.clear_current_task()
                _send({"type": "done"})
            elif t in ("error", "cancelled"):
                _dispatch_sse_to_tui(msg)
                session_logger.on_send(msg)
                runtime.clear_current_task()
                _send({"type": "done"})
            else:
                _dispatch_sse_to_tui(msg)
                session_logger.on_send(msg)
            continue

        # Handle stdin messages
        msg_type = msg.get("type", "")

        if msg_type == "quit":
            if runtime.current_task_id:
                client.cancel(runtime.current_task_id)
            client.close()
            try:
                SessionStore().update_meta(session_dir, status='completed')
            except Exception:
                pass
            _send({"type": "done"})
            break

        elif msg_type == "interrupt":
            if runtime.current_task_id:
                runtime.sse_shutdown.set()
                client.close_stream()
                client.cancel(runtime.current_task_id)
                runtime.clear_current_task()
            _send({"type": "done"})

        elif msg_type == "permission_response":
            if runtime.current_task_id:
                choice = msg.get("choice", "no")
                client.reply(runtime.current_task_id, choice)

        elif msg_type == "permission_mode":
            # In gateway mode, permission_mode changes cannot be forwarded via reply
            # Only update the mode display
            mode_str = msg.get("mode", "accept_edits")
            _send({"type": "status", "permission": mode_str})

        elif msg_type == "user_input":
            text = msg.get("text", "").strip()
            if not text:
                continue

            session_logger.on_user_input(text)  # capture user message even if gateway fails

            # user_input in waiting state → processed as reply
            if runtime.current_task_id:
                client.reply(runtime.current_task_id, text)
                continue

            # Create task (including slash commands — handled by gateway)
            try:
                data = client.create_task_payload(
                    task=text,
                    cwd=args.cwd,
                    model=args.model,
                    max_turns=args.max_turns,
                    parent_session_id=session_id,
                )
            except Exception as e:
                _send({"type": "error", "message": f"Task creation failed: {e}"})
                _send({"type": "done"})
                continue

            # Immediately processed commands (e.g., slash commands)
            if data.get("status") == "done" and data.get("task_id") == "instant":
                result = (data.get("result") or "").strip()
                if result:
                    _send({"type": "text", "content": result})
                _send({"type": "done"})
                continue

            task_id = data["task_id"]
            runtime.current_task_id = task_id
            # Create a new Event for each task. Reasons for not reusing the previous Event:
            # Sharing the same Event while the previous reader is shutting down causes a false early-exit.
            # The previous reader naturally exits upon receiving done/error/cancelled,
            # and the GC cleans up the previous Event.
            runtime.reset_sse_shutdown()

            sse_thread = threading.Thread(target=_sse_reader, args=(task_id,), daemon=True)
            sse_thread.start()


def main() -> None:
    # Parse cwd first (required to load project-local settings.json)
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--cwd", default=os.getcwd())
    pre_args, _ = pre.parse_known_args()

    from .config import load_settings
    cfg = load_settings(cwd=pre_args.cwd)

    parser = argparse.ArgumentParser(description="HermitAgent Bridge — Gateway HTTP client")
    parser.add_argument("--model", default="__auto__")
    parser.add_argument("--cwd", default=pre_args.cwd)
    parser.add_argument("--max-turns", type=int, default=cfg["max_turns"])
    parser.add_argument("--gateway-url", default=cfg["gateway_url"])
    parser.add_argument("--gateway-api-key", default=cfg["gateway_api_key"])
    # Legacy TUI compatibility — ignored arguments
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--yolo", action="store_true")
    parser.add_argument("--max-context", type=int, default=None)
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Disable auto-seed of previous-session handoff (sets HERMIT_SEED_HANDOFF=0)",
    )
    args = parser.parse_args()

    if args.no_seed:
        os.environ["HERMIT_SEED_HANDOFF"] = "0"

    if not args.gateway_url or not args.gateway_api_key:
        sys.stderr.write(
            "ERROR: gateway_url and gateway_api_key are required.\n"
            "Configure them in ~/.hermit/settings.json or .hermit/settings.json,\n"
            "or set environment variables HERMIT_GATEWAY_URL / HERMIT_GATEWAY_API_KEY.\n"
        )
        sys.exit(1)

    _run_gateway_mode(args)


if __name__ == "__main__":
    main()
