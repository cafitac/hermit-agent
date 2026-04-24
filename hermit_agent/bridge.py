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

from .channels_core.event_adapters import bridge_messages_from_sse_event  # noqa: E402
from .bridge_commands import build_bridge_commands  # noqa: E402
from .bridge_payloads import (  # noqa: E402
    build_interactive_message_request,
    build_interactive_session_request,
    build_ready_payload,
)
from .bridge_runtime import BridgeRuntime  # noqa: E402
from .bridge_services import (  # noqa: E402
    ensure_interactive_session,
    resolve_display_model,
    sync_tui_session_meta_from_interactive,
    submit_interactive_turn,
)


def _send(msg: dict) -> None:
    """Send JSON message to UI. Always uses the original stdout."""
    stream = _real_stdout or sys.stdout
    stream.write(json.dumps(msg, ensure_ascii=False) + "\n")
    stream.flush()


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
    display_model = resolve_display_model(
        requested_model=args.model,
        cwd=args.cwd,
        load_settings=load_settings,
        get_primary_model=get_primary_model,
    )

    if not client.check_gateway():
        _send({"type": "error", "message": f"Gateway connection failed: {args.gateway_url}"})
        _send({"type": "done"})
        return

    commands = build_bridge_commands()

    _send(build_ready_payload(model=display_model, cwd=args.cwd, version=VERSION, commands=commands))

    msg_queue: queue.Queue = queue.Queue()
    runtime = BridgeRuntime(msg_queue)

    # ── TUI session logging ──
    import uuid as _uuid
    from .session_store import SessionStore
    from .session_logger import SessionLogger as _SessionLogger
    store = SessionStore()
    session_id = _uuid.uuid4().hex[:12]
    session_dir = store.create_session(mode='tui', session_id=session_id, cwd=args.cwd)
    session_logger = _SessionLogger(session_dir=session_dir)

    def _stdin_reader() -> None:
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                msg_queue.put(json.loads(raw_line))
            except json.JSONDecodeError:
                continue

    def _interactive_sse_reader(session_id: str) -> None:
        for event in client.stream_interactive_events(session_id, runtime.sse_shutdown):
            runtime.msg_queue.put({"_source": "interactive_sse", **event})
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
        if msg.get("_source") in {"sse", "interactive_sse"}:
            t = msg.get("type")
            if t in ("waiting", "permission_ask"):
                runtime.mark_interactive_waiting()
            elif t in ("reply_ack", "done", "error", "cancelled"):
                runtime.clear_interactive_waiting()
            if t == "done":
                # done SSE result field → TUI text event (final response)
                result_text = (msg.get("result") or "").strip()
                session_logger.on_send(msg)  # capture final assistant response
                if result_text:
                    _send({"type": "text", "content": result_text})
                _send({"type": "stream_end"})
                sync_tui_session_meta_from_interactive(
                    store=store,
                    tui_session_dir=session_dir,
                    interactive_session_id=runtime.current_interactive_session_id,
                    cwd=args.cwd,
                    status="completed",
                )
                _send({"type": "done"})
            elif t in ("error", "cancelled"):
                _dispatch_sse_to_tui(msg)
                session_logger.on_send(msg)
                sync_tui_session_meta_from_interactive(
                    store=store,
                    tui_session_dir=session_dir,
                    interactive_session_id=runtime.current_interactive_session_id,
                    cwd=args.cwd,
                    status="completed" if t == "cancelled" else "error",
                )
                _send({"type": "done"})
            else:
                _dispatch_sse_to_tui(msg)
                session_logger.on_send(msg)
            continue

        # Handle stdin messages
        msg_type = msg.get("type", "")

        if msg_type == "quit":
            client.close()
            sync_tui_session_meta_from_interactive(
                store=store,
                tui_session_dir=session_dir,
                interactive_session_id=runtime.current_interactive_session_id,
                cwd=args.cwd,
                status='completed',
            )
            _send({"type": "done"})
            break

        elif msg_type == "interrupt":
            if runtime.current_interactive_session_id:
                runtime.sse_shutdown.set()
                client.close_stream()
                client.cancel_interactive_session(runtime.current_interactive_session_id)
                runtime.clear_interactive_waiting()
                sync_tui_session_meta_from_interactive(
                    store=store,
                    tui_session_dir=session_dir,
                    interactive_session_id=runtime.current_interactive_session_id,
                    cwd=args.cwd,
                    status='completed',
                )
            _send({"type": "done"})

        elif msg_type == "permission_response":
            if runtime.current_interactive_session_id and runtime.interactive_waiting:
                choice = msg.get("choice", "no")
                client.reply_interactive_session(runtime.current_interactive_session_id, choice)

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
            if runtime.current_interactive_session_id and runtime.interactive_waiting:
                client.reply_interactive_session(runtime.current_interactive_session_id, text)
                continue

            try:
                session_data = ensure_interactive_session(
                    client=client,
                    cwd=args.cwd,
                    model=args.model,
                    parent_session_id=session_id,
                    session_id=runtime.current_interactive_session_id,
                    build_interactive_session_request=build_interactive_session_request,
                )
            except Exception as e:
                _send({"type": "error", "message": f"Interactive session init failed: {e}"})
                _send({"type": "done"})
                continue

            runtime.current_interactive_session_id = session_data["session_id"]
            sync_tui_session_meta_from_interactive(
                store=store,
                tui_session_dir=session_dir,
                interactive_session_id=runtime.current_interactive_session_id,
                cwd=args.cwd,
                status='active',
            )
            try:
                submit_interactive_turn(
                    client=client,
                    session_id=runtime.current_interactive_session_id,
                    message=text,
                    build_interactive_message_request=build_interactive_message_request,
                )
            except Exception as e:
                _send({"type": "error", "message": f"Interactive turn failed: {e}"})
                _send({"type": "done"})
                continue

            runtime.reset_sse_shutdown()
            sse_thread = threading.Thread(
                target=_interactive_sse_reader,
                args=(runtime.current_interactive_session_id,),
                daemon=True,
            )
            sse_thread.start()
            continue


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
