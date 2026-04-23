from __future__ import annotations

from .codex_channels_adapter import install_codex_channels
from .install_flow import ensure_codex_marketplace_registered, remove_codex_reply_hook


def run_install_codex(*, cwd: str, codex_command: str = "codex", scope: str = "user") -> str:
    report = install_codex_channels(cwd=cwd, codex_command=codex_command, scope=scope)
    marketplace_status = ensure_codex_marketplace_registered(cwd=cwd, codex_command=codex_command, scope=scope)
    reply_hook_status = remove_codex_reply_hook(cwd=cwd)
    source_note = report.source_path or "none"
    return (
        "Hermit Codex integration is ready.\n\n"
        "Verified:\n"
        "- Codex-facing MCP surface: hermit-channel\n"
        f"- integration install mode: {report.install_mode}\n"
        f"- fallback source: {source_note}\n"
        f"- local integration files prepared under: {report.runtime_dir}\n"
        f"- settings updated: {report.settings_path}\n"
        f"- Codex discovery assets updated: {report.marketplace_path}\n"
        f"- Codex marketplace registration: {marketplace_status}\n"
        f"- legacy Codex reply hook: {reply_hook_status}\n"
        f"- local smoke check passed: {report.state_file}\n\n"
        "Next:\n"
        "1. restart Codex if it is already open\n"
        "2. run your normal Hermit Codex workflow\n"
    )
