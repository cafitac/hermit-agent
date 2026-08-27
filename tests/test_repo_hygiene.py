from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_npm_package_exposes_the_minimal_hermit_launcher() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["bin"] == {"hermit": "./bin/hermit.js"}
    assert (REPO_ROOT / "bin" / "hermit.js").is_file()
    assert not (REPO_ROOT / "hermit-ui" / "package.json").exists()


def test_readme_starts_with_supported_install_paths() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "hermit install claude" in readme
    assert "hermit install codex" in readme
    assert "hermit mcp-server" in readme
    assert "Claude Desktop" in readme
    assert "Claude Code, Codex, and\nClaude Desktop" in readme
    assert ".mcpb" in readme
    assert "React" not in readme
    assert "Hermes" not in readme
    assert "`hermit install claude` registers only Claude Code" in readme
    assert "hermit configure" in readme
    assert "Delegate one bounded task" in readme
    assert "does not create a task" in readme


def test_docs_contain_only_the_supported_user_guides() -> None:
    docs = sorted(path.relative_to(REPO_ROOT / "docs").as_posix() for path in (REPO_ROOT / "docs").rglob("*.md"))

    assert docs == ["architecture/overview.md", "cc-setup.md", "codex-setup.md"]


def test_legacy_cli_and_host_channel_modules_are_not_shipped() -> None:
    removed = (
        "hermit_agent/loop_commands/_workflow.py",
        "hermit_agent/gateway/task_commands.py",
        "hermit_agent/interfaces/telegram.py",
        "hermit_agent/sinks/codex_channels.py",
        "hermit_agent/codex_runner.py",
        "hermit_agent/codex_channels_adapter.py",
        "hermit_agent/channels_core/approvals.py",
        "hermit_agent/interactive_sinks/codex_app.py",
        "hermit_agent/auto_agents.py",
        "hermit_agent/tools/agent/subagent.py",
        "hermit_agent/codex/runner.py",
        "hermit_agent/autopilot.py",
        "hermit_agent/ralph.py",
        "hermit_agent/ultraqa.py",
    )

    assert all(not (REPO_ROOT / path).exists() for path in removed)
