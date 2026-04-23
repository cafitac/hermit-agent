"""HermitAgent — Local LLM Coding Agent

Usage:
  hermit_agent                            # React+Ink UI (default)
  hermit_agent "message"                  # Single message mode
  hermit_agent "message" --channel cli    # CLI channel (stdin/stdout, Standalone mode)
  hermit_agent --model qwen3:14b         # Specify model
  hermit_agent install                    # Guided setup/install flow
  hermit_agent setup-claude              # Prepare Hermit's Claude integration
  hermit_agent setup-codex               # Prepare Hermit's Codex integration
  hermit_agent --yolo                    # Run without permission checks
  hermit_agent --base-url http://server/v1  # Use remote Hermit gateway or custom endpoint

# CLI default base-url targets the local Hermit gateway.
# Bypass by setting HERMIT_LLM_URL or --base-url.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import TYPE_CHECKING

from .agent_session import CLIAgentSession
from .llm_client import create_llm_client
from .permissions import PermissionMode
from .session_store import SessionStore, _atomic_write_json
from .tui_render import compact_count_label

if TYPE_CHECKING:
    from .loop import AgentLoop

_GATEWAY_DEFAULT_URL = "http://localhost:8765/v1"


def _stdio_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HermitAgent — Local LLM Coding Agent")
    parser.add_argument("message", nargs="?", help="Single message to process")
    parser.add_argument("--model", default=None, help="Model name. Default: HERMIT_MODEL env var, else 'model' in ~/.hermit/settings.json.")
    parser.add_argument(
        "--base-url",
        default=_GATEWAY_DEFAULT_URL,
        help="API base URL (default: local Hermit gateway at http://localhost:8765/v1)",
    )
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--yolo", action="store_true", help="Skip all permission checks")
    parser.add_argument("--ask", action="store_true", help="Ask permission for every tool")
    parser.add_argument("--accept-edits", action="store_true", help="Auto-allow reads+edits, ask for bash")
    parser.add_argument("--dont-ask", action="store_true", help="Allow everything silently with logging")
    parser.add_argument("--plan", action="store_true", help="Read-only mode: block all write operations")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    parser.add_argument("--max-turns", type=int, default=50, help="Max agent turns (default: 50)")
    parser.add_argument("--max-context", type=int, default=32000, help="Max context tokens (default: 32000)")
    parser.add_argument("--fallback-model", default=None, help="Fallback model after 3 consecutive failures")
    parser.add_argument("--api-key", default=None, help="Bearer token for the Hermit gateway. Default: HERMIT_API_KEY env var, else gateway_api_key from ~/.hermit/settings.json.")
    parser.add_argument(
        "--channel",
        choices=["cli", "none"],
        default="none",
        help="Channel interface (cli: stdin/stdout bidirectional, none: existing mode)"
    )
    return parser




def _build_install_codex_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Hermit's Codex integration")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--codex-command", default="codex", help="Codex CLI command")
    parser.add_argument("--scope", choices=["workspace", "user"], default="user", help="Plugin bootstrap scope")
    return parser


def _build_install_claude_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Hermit's Claude integration")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--yes", action="store_true", help="Accept recommended installer choices non-interactively")
    parser.add_argument("--skip-mcp-register", action="store_true", help="Skip ~/.claude.json registration")
    return parser


def _build_install_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guided Hermit install/setup flow")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--codex-command", default="codex", help="Codex CLI command")
    parser.add_argument("--codex-scope", choices=["workspace", "user"], default="user", help="Codex plugin bootstrap scope")
    parser.add_argument("--yes", action="store_true", help="Accept recommended installer choices non-interactively")
    parser.add_argument("--skip-mcp-register", action="store_true", help="Skip ~/.claude.json MCP registration")
    parser.add_argument("--skip-codex", action="store_true", help="Skip Hermit's internal Codex async runtime install/refresh")
    return parser


def _build_pending_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show Hermit-managed pending interactions")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    return parser


def _build_status_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show Hermit operator status")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--watch", action="store_true", help="Refresh the status continuously until interrupted")
    parser.add_argument("--interval", type=float, default=1.0, help="Watch refresh interval in seconds (default: 1.0)")
    return parser


def _build_doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose or repair Hermit setup")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--fix", action="store_true", help="Attempt common setup/runtime repairs automatically")
    return parser


def parse_args(argv=None):
    """Parse CLI arguments. Pass argv list for testing; omit to read sys.argv."""
    return _build_parser().parse_args(argv)


def run_single(agent: AgentLoop, message: str):
    """Single message mode."""
    store = SessionStore()
    sd = store.create_session(mode='single', session_id=agent.session_id, cwd=agent.cwd, model=agent.llm.model)
    try:
        response = agent.run(message)
        if not agent.streaming:
            print(response)
        if agent.messages:
            try:
                _atomic_write_json(
                    os.path.join(sd, 'messages.json'),
                    agent.messages,
                )
                # Extract preview from first user message
                preview = ''
                for msg in agent.messages:
                    if msg.get('role') == 'user' and isinstance(msg.get('content'), str):
                        preview = msg['content'][:80]
                        break
                store.update_meta(sd, status='completed', turn_count=agent.turn_count, preview=preview)
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)


def _resolve_api_key(args) -> str | None:
    if args.api_key:
        return args.api_key
    env = os.environ.get("HERMIT_API_KEY")
    if env:
        return env
    try:
        from .config import load_settings
        return load_settings(cwd=os.getcwd()).get("gateway_api_key") or None
    except Exception:
        return None


def _resolve_model(args) -> str:
    if args.model:
        return args.model
    from .config import load_settings
    return load_settings(cwd=os.getcwd()).get("model") or "qwen3-coder:30b"


def _should_auto_use_cli_channel(args) -> bool:
    if getattr(args, "channel", "none") != "none":
        return False
    if not getattr(args, "message", None):
        return False
    return _stdio_interactive()


def _prompt_idle_menu_choice(*, pending_count: int = 0, repair_recommended: bool = False) -> str:
    pending_label = f"Answer pending interactions ({compact_count_label('count', pending_count)})" if pending_count else "Show pending interactions"
    repair_label = "Repair setup (recommended)" if repair_recommended else "Repair setup (doctor --fix)"
    print("[Hermit] What would you like to do?")
    print(f"  1. {pending_label}")
    print("  2. Show status")
    print(f"  3. {repair_label}")
    print("  4. Start a new task")
    print("  5. Exit")
    try:
        return input("Choice: ").strip()
    except (EOFError, KeyboardInterrupt):
        return "5"


def _render_idle_menu_state(*, cwd: str) -> dict[str, object]:
    from .install_flow import run_startup_self_heal
    from .pending_interactions import get_pending_interactions, _summarize_interaction

    heal = run_startup_self_heal(cwd=cwd)
    pending = get_pending_interactions(cwd=cwd)
    repair_recommended = (
        heal.gateway_status != "healthy"
        or heal.mcp_registration_status != "registered"
        or heal.codex_runtime_status != "installed"
    )
    latest_preview = _summarize_interaction(pending[0], max_chars=50) if pending else None
    return {
        "pending_count": len(pending),
        "repair_recommended": repair_recommended,
        "latest_preview": latest_preview,
    }


def _prompt_new_task_message() -> str:
    try:
        return input("Task: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _derive_permission_mode(args) -> PermissionMode:
    if args.yolo:
        return PermissionMode.YOLO
    if args.ask:
        return PermissionMode.ASK
    if args.accept_edits:
        return PermissionMode.ACCEPT_EDITS
    if args.dont_ask:
        return PermissionMode.DONT_ASK
    if args.plan:
        return PermissionMode.PLAN
    return PermissionMode.ALLOW_READ


def _run_message_mode(*, args, message: str) -> None:
    llm = create_llm_client(base_url=args.base_url, model=args.model, api_key=args.api_key)
    if args.fallback_model:
        llm.fallback_model = args.fallback_model

    channel = None
    if args.channel == "cli" or _stdio_interactive():
        from .interfaces import CLIChannel
        channel = CLIChannel()

    session = CLIAgentSession(
        llm=llm,
        cwd=args.cwd,
        permission_mode=_derive_permission_mode(args),
        channel=channel,
        max_turns=args.max_turns,
        max_context_tokens=args.max_context,
        streaming=not args.no_stream,
    )

    if channel:
        channel.start()
    try:
        result = session.run(message)
        if not session._agent or not session._agent.streaming:
            print(result)
        else:
            print()
        if session._agent and session._agent.messages:
            try:
                store = SessionStore()
                sd = store.create_session(
                    mode='single',
                    session_id=session._agent.session_id,
                    cwd=args.cwd,
                    model=llm.model,
                )
                _atomic_write_json(
                    os.path.join(sd, 'messages.json'),
                    session._agent.messages,
                )
                preview = ''
                for msg in session._agent.messages:
                    if msg.get('role') == 'user' and isinstance(msg.get('content'), str):
                        preview = msg['content'][:80]
                        break
                store.update_meta(sd, status='completed', turn_count=session._agent.turn_count, preview=preview)
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\n[Interrupted]")
    finally:
        if channel:
            channel.stop()


def _run_idle_menu(*, cwd: str) -> str:
    from .doctor import format_doctor_fix_summary
    from .pending_interactions import build_operator_status_summary, build_pending_interaction_summary

    state = _render_idle_menu_state(cwd=cwd)
    latest_preview = state["latest_preview"]
    pending_count = state["pending_count"] if isinstance(state["pending_count"], int) else 0
    if latest_preview:
        print(f"[Hermit] latest pending: {latest_preview}")
    choice = _prompt_idle_menu_choice(
        pending_count=pending_count,
        repair_recommended=bool(state["repair_recommended"]),
    )
    if choice == "1":
        print(build_pending_interaction_summary(cwd=cwd))
        return "handled"
    if choice == "2":
        print(build_operator_status_summary(cwd=cwd))
        return "handled"
    if choice == "3":
        print(format_doctor_fix_summary(cwd=cwd))
        return "handled"
    if choice == "4":
        return "task"
    return "exit"


def _run_idle_menu_loop(*, args) -> None:
    while True:
        action = _run_idle_menu(cwd=args.cwd)
        if action == "task":
            message = _prompt_new_task_message()
            if message:
                _run_message_mode(args=args, message=message)
            continue
        if action == "handled":
            continue
        if action == "exit":
            return


def _run_status_watch(*, cwd: str, interval: float) -> None:
    from .pending_interactions import build_operator_status_summary

    first = True
    try:
        while True:
            if first:
                first = False
            else:
                print("\x1b[H\x1b[J", end="")
            print(build_operator_status_summary(cwd=cwd))
            time.sleep(max(0.1, interval))
    except KeyboardInterrupt:
        print("\n[Hermit] Stopped status watch.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from .install_flow import format_install_summary, run_install

        install_args = _build_install_parser().parse_args(sys.argv[2:])
        summary = run_install(
            cwd=install_args.cwd,
            codex_command=install_args.codex_command,
            codex_scope=install_args.codex_scope,
            assume_yes=install_args.yes,
            skip_mcp_register=install_args.skip_mcp_register,
            skip_codex=install_args.skip_codex,
        )
        print(format_install_summary(summary))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "pending":
        from .pending_interactions import build_pending_interaction_summary

        pending_args = _build_pending_parser().parse_args(sys.argv[2:])
        print(build_pending_interaction_summary(cwd=pending_args.cwd))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        from .pending_interactions import build_operator_status_summary

        status_args = _build_status_parser().parse_args(sys.argv[2:])
        if status_args.watch:
            _run_status_watch(cwd=status_args.cwd, interval=status_args.interval)
        else:
            print(build_operator_status_summary(cwd=status_args.cwd))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from .doctor import format_doctor_fix_summary, run_diagnostics

        doctor_args = _build_doctor_parser().parse_args(sys.argv[2:])
        if doctor_args.fix:
            print(format_doctor_fix_summary(cwd=doctor_args.cwd))
        else:
            print(run_diagnostics(cwd=doctor_args.cwd).format())
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"setup-claude", "install-claude"}:
        from .install_claude import run_install_claude

        install_args = _build_install_claude_parser().parse_args(sys.argv[2:])
        print(run_install_claude(cwd=install_args.cwd, assume_yes=install_args.yes, skip_mcp_register=install_args.skip_mcp_register))
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"setup-codex", "install-codex"}:
        from .install_codex import run_install_codex

        install_args = _build_install_codex_parser().parse_args(sys.argv[2:])
        print(run_install_codex(cwd=install_args.cwd, codex_command=install_args.codex_command, scope=install_args.scope))
        return

    args = parse_args()
    from .install_flow import format_startup_heal_summary, run_startup_self_heal

    startup_heal = run_startup_self_heal(cwd=args.cwd)
    if startup_heal.changed and os.environ.get("HERMIT_QUIET_STARTUP_HEAL", "").lower() not in {"1", "true", "yes"}:
        print(format_startup_heal_summary(startup_heal), file=sys.stderr)

    if not args.message and _stdio_interactive():
        from .pending_interactions import build_idle_operator_overview, run_pending_interaction_loop

        handled = run_pending_interaction_loop(cwd=args.cwd)
        if handled:
            print("[Hermit] Pending interaction queue is clear.")
        print(build_idle_operator_overview(cwd=args.cwd))
        _run_idle_menu_loop(args=args)
        return

    args.api_key = _resolve_api_key(args)
    args.model = _resolve_model(args)

    if args.message:
        _run_message_mode(args=args, message=args.message)
    else:
        # REPL mode is handled by hermit_agent.sh → React+Ink UI
        print("Use 'hermit_agent' command for interactive mode (React+Ink UI)")
        print("Or: hermit_agent \"message\" for single message mode")


if __name__ == "__main__":
    main()
