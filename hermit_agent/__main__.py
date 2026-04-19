"""HermitAgent — Local LLM Coding Agent

Usage:
  hermit_agent                            # React+Ink UI (default)
  hermit_agent "message"                  # Single message mode
  hermit_agent "message" --channel cli    # CLI channel (stdin/stdout, Standalone mode)
  hermit_agent --model qwen3:14b         # Specify model
  hermit_agent --yolo                    # Run without permission checks
  hermit_agent --base-url http://server/v1  # Use remote Hermit gateway or custom endpoint

# CLI default base-url targets the local Hermit gateway.
# Bypass by setting HERMIT_LLM_URL or --base-url.
"""

from __future__ import annotations

import argparse
import os
import sys

from .agent_session import CLIAgentSession
from .llm_client import create_llm_client
from .permissions import PermissionMode
from .session import save_session

_GATEWAY_DEFAULT_URL = "http://localhost:8765/v1"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HermitAgent — Local LLM Coding Agent")
    parser.add_argument("message", nargs="?", help="Single message to process")
    parser.add_argument("--model", default="qwen3-coder:30b", help="Model name (default: qwen3-coder:30b)")
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
    parser.add_argument("--api-key", default=os.environ.get("HERMIT_API_KEY"), help="Bearer token for the Hermit gateway (needed when the gateway is reached over ngrok or similar)")
    parser.add_argument(
        "--channel",
        choices=["cli", "none"],
        default="none",
        help="Channel interface (cli: stdin/stdout bidirectional, none: existing mode)"
    )
    return parser


def parse_args(argv=None):
    """Parse CLI arguments. Pass argv list for testing; omit to read sys.argv."""
    return _build_parser().parse_args(argv)


def run_single(agent: AgentLoop, message: str):
    """Single message mode."""
    try:
        response = agent.run(message)
        if not agent.streaming:
            print(response)
        if agent.messages:
            try:
                save_session(
                    session_id=agent.session_id,
                    messages=agent.messages,
                    system_prompt=agent.system_prompt,
                    model=agent.llm.model,
                    cwd=agent.cwd,
                    turn_count=agent.turn_count,
                )
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)


def main():
    args = parse_args()

    if args.yolo:
        perm_mode = PermissionMode.YOLO
    elif args.ask:
        perm_mode = PermissionMode.ASK
    elif args.accept_edits:
        perm_mode = PermissionMode.ACCEPT_EDITS
    elif args.dont_ask:
        perm_mode = PermissionMode.DONT_ASK
    elif args.plan:
        perm_mode = PermissionMode.PLAN
    else:
        perm_mode = PermissionMode.ALLOW_READ

    llm = create_llm_client(base_url=args.base_url, model=args.model, api_key=args.api_key)
    if args.fallback_model:
        llm.fallback_model = args.fallback_model

    # Channel interface setup
    channel = None
    if args.channel == "cli":
        from .interfaces import CLIChannel
        channel = CLIChannel()

    session = CLIAgentSession(
        llm=llm,
        cwd=args.cwd,
        permission_mode=perm_mode,
        channel=channel,
        max_turns=args.max_turns,
        max_context_tokens=args.max_context,
        streaming=not args.no_stream,
    )

    if args.message:
        if channel:
            channel.start()
        try:
            result = session.run(args.message)
            if not session._agent or not session._agent.streaming:
                print(result)
            if session._agent and session._agent.messages:
                try:
                    save_session(
                        session_id=session._agent.session_id,
                        messages=session._agent.messages,
                        system_prompt=session._agent.system_prompt,
                        model=llm.model,
                        cwd=args.cwd,
                        turn_count=session._agent.turn_count,
                    )
                except Exception:
                    pass
        except KeyboardInterrupt:
            print("\n[Interrupted]")
        finally:
            if channel:
                channel.stop()
    else:
        # REPL mode is handled by hermit_agent.sh → React+Ink UI
        print("Use 'hermit_agent' command for interactive mode (React+Ink UI)")
        print("Or: hermit_agent \"message\" for single message mode")


if __name__ == "__main__":
    main()
