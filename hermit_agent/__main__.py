"""HermitAgent — Local LLM Coding Agent

Usage:
  hermit_agent                            # React+Ink UI (default)
  hermit_agent "message"                  # Single message mode
  hermit_agent "message" --channel cli    # CLI channel (stdin/stdout, Standalone mode)
  hermit_agent mcp-server                 # MCP stdio server via the stable Hermit CLI surface
  hermit_agent --model qwen3:14b         # Specify model
  hermit_agent install                    # Guided setup/install flow (Claude + Codex)
  hermit_agent --yolo                    # Run without permission checks
  hermit_agent --base-url http://server/v1  # Use remote Hermit gateway or custom endpoint

# CLI default base-url targets the local Hermit gateway.
# Bypass by setting HERMIT_LLM_URL or --base-url.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import TYPE_CHECKING

from .version import VERSION
from .agent_session import CLIAgentSession
from .llm_client import create_llm_client
from .permissions import PermissionMode
from .session_store import SessionStore
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
    parser.add_argument("--version", action="version", version=f"hermit {VERSION}")
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




def _build_install_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guided Hermit install/setup flow")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    parser.add_argument("--hermes-home", default=None, help="Optional Hermes Agent home directory for isolated MCP registration/smoke")
    parser.add_argument("--codex-command", default="codex", help="Codex CLI command")
    parser.add_argument("--codex-scope", choices=["workspace", "user"], default="user", help="Codex plugin bootstrap scope")
    parser.add_argument("--yes", action="store_true", help="Accept recommended installer choices non-interactively")
    parser.add_argument("--skip-mcp-register", action="store_true", help="Skip ~/.claude.json MCP registration")
    parser.add_argument("--skip-codex", action="store_true", help="Skip Hermit's internal Codex async runtime install/refresh")
    parser.add_argument("--skip-agent-learner", action="store_true", help="Skip agent-learner hook installation/refresh")
    parser.add_argument("--print-hermes-mcp-config", action="store_true", help="Print Hermes Agent MCP registration snippet and exit without changing files")
    parser.add_argument("--fix-hermes-mcp", action="store_true", help="Explicitly register Hermit MCP with Hermes Agent via `hermes mcp add`")
    parser.add_argument("--test-hermes-mcp", action="store_true", help="Run Hermes Agent's live `hermes mcp test hermit-channel` probe without changing config")
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
    parser.add_argument("--hermes-home", default=None, help="Optional Hermes Agent config directory for isolated MCP diagnostics/repairs")
    return parser


def _build_config_local_backend_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermit_agent config local-backend", description="Configure local LLM backend")
    parser.add_argument("--set", dest="set_backend", choices=["mlx", "llama_cpp", "ollama"], help="Explicitly set backend")
    parser.add_argument("--list", dest="list_backends", action="store_true", help="List all detected backends")
    parser.add_argument("--re-detect", dest="re_detect", action="store_true", help="Re-run auto-detection")
    parser.add_argument("--cwd", default=os.getcwd())
    return parser


def _run_config_local_backend(args: argparse.Namespace) -> None:
    from .local_runtime import detect_all_runtimes, detect_local_runtime, get_install_hints, BACKEND_MLX, BACKEND_LLAMA_CPP, BACKEND_OLLAMA
    from .config import load_settings, apply_detected_backend, GLOBAL_SETTINGS_PATH, init_settings_file

    cfg = load_settings(cwd=args.cwd)

    if args.list_backends:
        all_runtimes = detect_all_runtimes()
        print("Detected local LLM backends:")
        for rt in all_runtimes:
            if rt.available:
                print(f"  {rt.backend}: {rt.base_url} (port {rt.default_port})")
            else:
                hint = get_install_hints(rt.backend or "")
                hint_suffix = f" — install: {hint}" if hint else ""
                print(f"  {rt.backend}: not available{hint_suffix}")
        return

    if args.re_detect or args.set_backend:
        if args.set_backend:
            # Force a specific backend by probing all and picking the matching one
            all_runtimes = detect_all_runtimes()
            target = next((r for r in all_runtimes if r.backend == args.set_backend), None)
            if target is None or not target.available:
                hint = get_install_hints(args.set_backend)
                print(f"Backend '{args.set_backend}' is not available.")
                if hint:
                    print(f"Install hint: {hint}")
                return
            chosen = target
        else:
            chosen = detect_local_runtime()
            all_runtimes = detect_all_runtimes()

        if not chosen.available:
            print("No local LLM backend detected.")
            print("Install one of:")
            for backend, hint in [(BACKEND_MLX, get_install_hints(BACKEND_MLX)), (BACKEND_LLAMA_CPP, get_install_hints(BACKEND_LLAMA_CPP)), (BACKEND_OLLAMA, get_install_hints(BACKEND_OLLAMA))]:
                if hint:
                    print(f"  {backend}: {hint}")
            return

        cfg = apply_detected_backend(cfg, chosen, all_runtimes if args.re_detect else [chosen])
        # Write to global settings
        settings_path = GLOBAL_SETTINGS_PATH
        if not settings_path.exists():
            init_settings_file(global_=True)
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        payload["local_backend"] = cfg["local_backend"]
        payload["local_llm_url"] = cfg["local_llm_url"]
        if cfg.get("local_model"):
            payload["local_model"] = cfg["local_model"]
        settings_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Local backend set to: {chosen.backend} ({chosen.base_url})")
        return

    # Default: show current config
    current = cfg.get("local_backend") or "(not configured)"
    url = cfg.get("local_llm_url") or "(not set)"
    auto = cfg.get("local_backend_auto_detected", False)
    print(f"Current local backend: {current}")
    print(f"  URL: {url}")
    print(f"  Auto-detected: {'yes' if auto else 'no'}")
    print("")
    print("Use --list to see available backends, --re-detect to auto-detect, or --set <backend> to choose.")


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
                store.update_transcript_state(
                    sd,
                    messages=agent.messages,
                    turn_count=agent.turn_count,
                    status='completed',
                )
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)
    finally:
        _print_token_summary(agent)


def _print_token_summary(agent) -> None:
    t = getattr(agent, "token_totals", {})
    if not t:
        return
    inp = t.get("prompt_tokens", 0)
    out = t.get("completion_tokens", 0)
    if not inp and not out:
        return
    cached = t.get("cached_tokens", 0)
    reasoning = t.get("reasoning_tokens", 0)
    total = inp + out
    cached_str = f" (+ {cached:,} cached)" if cached else ""
    reasoning_str = f" (reasoning {reasoning:,})" if reasoning else ""
    print(f"\nToken usage: total={total:,} input={inp:,}{cached_str} output={out:,}{reasoning_str}", file=sys.stderr)


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
    from .config import get_primary_model, load_settings

    cfg = load_settings(cwd=os.getcwd())
    configured = str(cfg.get("model", "") or "").strip()
    if configured == "__auto__":
        return get_primary_model(cfg, available_only=True) or get_primary_model(cfg) or "qwen3-coder:30b"
    if configured:
        return configured
    return get_primary_model(cfg, available_only=True) or get_primary_model(cfg) or "qwen3-coder:30b"


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


def _prompt_guided_install(*, startup_heal) -> bool:
    if not getattr(startup_heal, "guided_install_recommended", False):
        return False
    print("[Hermit] Claude Code or Codex integration is not fully set up yet.")
    try:
        answer = input("Run guided setup now and configure both integrations? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"", "y", "yes"}


def _maybe_run_guided_install(*, args, startup_heal) -> bool:
    if not _stdio_interactive():
        return False
    if not getattr(startup_heal, "guided_install_recommended", False):
        return False
    if not _prompt_guided_install(startup_heal=startup_heal):
        return False

    from .install_flow import format_install_summary, run_install

    summary = run_install(
        cwd=args.cwd,
        codex_command="codex",
        codex_scope="user",
        assume_yes=False,
        skip_mcp_register=False,
        skip_codex=False,
    )
    print(format_install_summary(summary))
    return True


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
                store.update_transcript_state(
                    sd,
                    messages=session._agent.messages,
                    turn_count=session._agent.turn_count,
                    status='completed',
                )
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


def _extract_cwd(argv: list[str]) -> str:
    """Extract ``--cwd`` / ``--cwd=`` from *argv*, falling back to ``os.getcwd()``."""
    i = 0
    while i < len(argv):
        if argv[i] == "--cwd" and i + 1 < len(argv):
            return argv[i + 1]
        if argv[i].startswith("--cwd="):
            return argv[i].split("=", 1)[1]
        i += 1
    return os.getcwd()


def _dispatch_codex_channels() -> None:
    """Handle `hermit_agent codex-channels {install|status|start|stop}`."""
    args = sys.argv[2:]
    handlers = {
        "install": _run_codex_channels_install,
        "status": _run_codex_channels_status,
        "start": _run_codex_channels_start,
        "stop": _run_codex_channels_stop,
    }

    sub = args[0] if args else None
    if sub not in handlers:
        print(
            "Usage: hermit_agent codex-channels {install|status|start|stop}",
            file=sys.stderr,
        )
        sys.exit(1)

    cwd = _extract_cwd(args[1:])
    handlers[sub](cwd=cwd)


def _run_codex_channels_install(*, cwd: str, codex_command: str = "codex") -> None:
    from .codex.channels_adapter import install_codex_channels

    try:
        report = install_codex_channels(cwd=cwd, codex_command=codex_command)
        print(f"codex-channels: installed ({report.install_mode})")
        print(f"  runtime:  {report.runtime_dir}")
        print(f"  settings: {report.settings_path}")
        print(f"  serve:    {' '.join(report.serve_command)}")
    except Exception as exc:
        print(f"codex-channels install failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _load_codex_channels_settings(cwd: str):
    """Load merged codex-channels settings for *cwd*."""
    from .codex.channels_adapter import load_codex_channels_settings
    from .config import load_settings

    return load_codex_channels_settings(load_settings(cwd=cwd), cwd)


def _codex_channels_runtime_dir(settings, cwd: str):
    """Resolve the runtime directory for codex-channels."""
    from pathlib import Path

    return Path(settings.runtime_dir) if settings.runtime_dir else Path(cwd) / ".hermit"


def _run_codex_channels_status(*, cwd: str) -> None:
    import urllib.request

    settings = _load_codex_channels_settings(cwd)
    if not settings.enabled:
        print("codex-channels: disabled")
        return

    addr = f"http://{settings.host}:{settings.port}"
    try:
        with urllib.request.urlopen(f"{addr}/health", timeout=2) as resp:
            if resp.status == 200:
                print(f"codex-channels: reachable ({addr})")
                return
    except Exception:
        pass
    print(f"codex-channels: unreachable ({addr})")
    raise SystemExit(1)


def _run_codex_channels_start(*, cwd: str) -> None:
    import subprocess

    settings = _load_codex_channels_settings(cwd)
    from .codex.channels_adapter import build_runtime_serve_command

    serve_cmd = build_runtime_serve_command(settings=settings)
    proc = subprocess.Popen(serve_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    runtime_dir = _codex_channels_runtime_dir(settings, cwd)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_file = runtime_dir / "codex-channels.pid"
    pid_file.write_text(str(proc.pid))
    print(f"codex-channels: started (pid={proc.pid}, pid_file={pid_file})")


def _run_codex_channels_stop(*, cwd: str) -> None:
    import os as _os
    import signal

    settings = _load_codex_channels_settings(cwd)
    runtime_dir = _codex_channels_runtime_dir(settings, cwd)
    pid_file = runtime_dir / "codex-channels.pid"
    if not pid_file.exists():
        print("codex-channels: not running (no pid file)")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        print("codex-channels: invalid pid file, removed")
        return

    try:
        _os.kill(pid, signal.SIGTERM)
        print(f"codex-channels: stopped (pid={pid})")
    except ProcessLookupError:
        print(f"codex-channels: process {pid} not found (stale pid)")
    finally:
        pid_file.unlink(missing_ok=True)


def _dispatch_learner() -> None:
    """Handle `hermit_agent learner {init|status|dashboard|process|inject}`."""
    import shutil
    import subprocess

    _VALID_SUBS = {"init", "status", "dashboard", "process", "inject"}

    argv = sys.argv[2:]
    sub = argv[0] if argv else "status"
    if sub not in _VALID_SUBS:
        print(
            f"Usage: hermit_agent learner {{{('|'.join(sorted(_VALID_SUBS)))}}}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not shutil.which("agent-learner"):
        print(
            "agent-learner is not installed. Run:\n"
            "  pip install agent-learner\n"
            "or\n"
            "  pip install -e ~/Project/agent-learner",
            file=sys.stderr,
        )
        sys.exit(1)

    extra = argv[1:]
    cmd = ["agent-learner", sub, "--project-root", os.getcwd()] + extra
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from .install_flow import (
            ensure_hermes_mcp_registered,
            format_hermes_mcp_config_snippet,
            format_hermes_mcp_fix_summary,
            format_hermes_mcp_test_summary,
            format_install_summary,
            run_hermes_mcp_connection_test,
            run_install,
        )

        install_args = _build_install_parser().parse_args(sys.argv[2:])
        if install_args.print_hermes_mcp_config:
            print(format_hermes_mcp_config_snippet(cwd=install_args.cwd))
            return
        if install_args.fix_hermes_mcp:
            print(format_hermes_mcp_fix_summary(ensure_hermes_mcp_registered(cwd=install_args.cwd, hermes_home=install_args.hermes_home)))
            return
        if install_args.test_hermes_mcp:
            print(format_hermes_mcp_test_summary(run_hermes_mcp_connection_test(cwd=install_args.cwd, hermes_home=install_args.hermes_home)))
            return
        summary = run_install(
            cwd=install_args.cwd,
            codex_command=install_args.codex_command,
            codex_scope=install_args.codex_scope,
            assume_yes=install_args.yes,
            skip_mcp_register=install_args.skip_mcp_register,
            skip_codex=install_args.skip_codex,
            skip_agent_learner=install_args.skip_agent_learner,
            hermes_home=install_args.hermes_home,
        )
        print(format_install_summary(summary))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "mcp-server":
        from .mcp_launcher import main as run_mcp_server

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        run_mcp_server()
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

    if len(sys.argv) > 2 and sys.argv[1] == "config" and sys.argv[2] == "local-backend":
        config_args = _build_config_local_backend_parser().parse_args(sys.argv[3:])
        _run_config_local_backend(args=config_args)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from .doctor import format_doctor_fix_summary, run_diagnostics

        doctor_args = _build_doctor_parser().parse_args(sys.argv[2:])
        if doctor_args.fix:
            print(format_doctor_fix_summary(cwd=doctor_args.cwd, hermes_home=doctor_args.hermes_home))
        else:
            print(run_diagnostics(cwd=doctor_args.cwd, hermes_home=doctor_args.hermes_home).format())
        return

    # ── codex-channels dispatch ──────────────────────────────────────
    if len(sys.argv) > 1 and sys.argv[1] == "codex-channels":
        _dispatch_codex_channels()
        return

    # ── learner dispatch ─────────────────────────────────────────────
    if len(sys.argv) > 1 and sys.argv[1] == "learner":
        _dispatch_learner()
        return

    args = parse_args()
    from .install_flow import format_startup_heal_summary, run_startup_self_heal

    startup_heal = run_startup_self_heal(cwd=args.cwd)
    if startup_heal.changed and os.environ.get("HERMIT_QUIET_STARTUP_HEAL", "").lower() not in {"1", "true", "yes"}:
        print(format_startup_heal_summary(startup_heal), file=sys.stderr)

    if not args.message and _stdio_interactive():
        _maybe_run_guided_install(args=args, startup_heal=startup_heal)
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
