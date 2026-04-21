from __future__ import annotations

from .codex_channels_adapter import install_codex_channels


def run_install_codex(*, cwd: str, codex_command: str = "codex", scope: str = "workspace") -> str:
    report = install_codex_channels(cwd=cwd, codex_command=codex_command, scope=scope)
    source_note = report.source_path or "packaged runtime"
    return (
        "Codex path is ready.\n\n"
        "Verified:\n"
        f"- codex-channels source: {source_note}\n"
        f"- runtime installed under: {report.runtime_dir}\n"
        f"- settings updated: {report.settings_path}\n"
        f"- plugin bootstrap installed: {report.marketplace_path}\n"
        f"- codex-channels runtime smoke passed: {report.state_file}\n\n"
        "Next:\n"
        "1. restart Codex if it is already open\n"
        "2. run your normal Hermit Codex workflow\n"
    )
