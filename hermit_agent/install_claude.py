from __future__ import annotations

from .install_flow import format_install_summary, run_install


def run_install_claude(*, cwd: str, assume_yes: bool = False, skip_mcp_register: bool = False) -> str:
    summary = run_install(
        cwd=cwd,
        assume_yes=assume_yes,
        skip_mcp_register=skip_mcp_register,
        skip_codex=True,
    )
    return format_install_summary(summary)
