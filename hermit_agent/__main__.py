"""Command line for the Hermit MCP executor.

Hermit deliberately has no standalone chat or terminal UI.  It is installed
into Claude Code or Codex and used from the host agent through MCP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .mcp_install import (
    VALID_INSTALL_TARGETS,
    doctor_report,
    format_doctor_summary,
    format_install_summary,
    inspect_mcp_install,
    install_mcp_host,
)
from .config import configure_openai_compatible_provider
from .version import VERSION


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermit",
        description="Hermit — a cost-optimized MCP coding executor for Claude Code and Codex.",
    )
    parser.add_argument("--version", action="version", version=f"hermit {VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    install = subparsers.add_parser("install", help="Register Hermit MCP with Claude Code or Codex")
    install.add_argument("target", nargs="?", default="all", choices=VALID_INSTALL_TARGETS)
    install.add_argument("--cwd", default=os.getcwd(), help="Workspace used when the executor receives a task")
    install.add_argument("--claude-command", default="claude", help="Claude Code CLI command (default: claude)")
    install.add_argument("--codex-command", default="codex", help="Codex CLI command (default: codex)")

    doctor = subparsers.add_parser("doctor", help="Check Claude Code, Codex, and gateway MCP readiness")
    doctor.add_argument("--cwd", default=os.getcwd())
    doctor.add_argument("--claude-command", default="claude", help="Claude Code CLI command (default: claude)")
    doctor.add_argument("--codex-command", default="codex", help="Codex CLI command (default: codex)")
    doctor.add_argument("--json", action="store_true", dest="json_output", help="Emit a paste-safe machine-readable readiness report")

    configure = subparsers.add_parser("configure", help="Configure an OpenAI-compatible executor without storing its API key")
    configure.add_argument("--model", required=True, help="Executor model name")
    configure.add_argument("--base-url", required=True, help="OpenAI-compatible Chat Completions base URL")
    configure.add_argument("--api-key-env", required=True, help="Environment variable containing the API key")
    configure.add_argument("--provider", default="openai-compatible", help="Stable local name for this provider")

    subparsers.add_parser("mcp-server", help="Run the Hermit MCP server over stdio")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "mcp-server":
        from .mcp_launcher import main as run_mcp_server

        run_mcp_server()
        return
    if args.command == "install":
        summary = install_mcp_host(
            target=args.target,
            cwd=args.cwd,
            claude_command=args.claude_command,
            codex_command=args.codex_command,
        )
        print(format_install_summary(summary))
        raise SystemExit(0 if summary.succeeded else 1)
    if args.command == "doctor":
        summary = inspect_mcp_install(
            cwd=args.cwd,
            claude_command=args.claude_command,
            codex_command=args.codex_command,
        )
        if args.json_output:
            print(json.dumps(doctor_report(summary), ensure_ascii=False, indent=2))
        else:
            print(format_doctor_summary(summary))
        raise SystemExit(0 if summary.succeeded and summary.gateway_status == "healthy" else 1)
    if args.command == "configure":
        try:
            path = configure_openai_compatible_provider(
                model=args.model,
                base_url=args.base_url,
                api_key_env=args.api_key_env,
                provider_name=args.provider,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Configured {args.model} through {args.provider}. API key remains in ${args.api_key_env}; settings: {path}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
