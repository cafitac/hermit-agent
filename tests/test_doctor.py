"""hermit_agent.doctor — HermitAgent installation/configuration diagnostic test.

`run_diagnostics(cwd, home)` iterates through the Check list and returns a DiagReport containing the
PASS/WARN/FAIL status and reason message for each item.

Red-Green:
1. Missing hermit_agent/doctor.py → Red
2. Minimal implementation → Green
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.doctor import DiagStatus, run_diagnostics


def _fresh_env(project_dir: str, home: str) -> dict:
    """Environment isolation helper to prevent HOME interference during tests."""
    return {"cwd": project_dir, "home": home}


def test_report_has_expected_axes():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(**_fresh_env(project, home))
        axis_names = {c.name for c in report.checks}
        assert {
            "HERMIT.md",
            "~/.hermit dir",
            "hooks.json",
            "skills",
            "permissions.sensitive_deny",
            "Hermes MCP",
        }.issubset(axis_names)


def test_hermit_agent_md_present_in_project_passes():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        (Path(project) / "HERMIT.md").write_text("# project")
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "HERMIT.md")
        assert chk.status == DiagStatus.PASS


def test_hermit_agent_md_absent_warns():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "HERMIT.md")
        assert chk.status in (DiagStatus.WARN, DiagStatus.FAIL)


def test_home_hermit_agent_dir_missing_warns():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "~/.hermit dir")
        assert chk.status == DiagStatus.WARN


def test_home_hermit_agent_dir_present_passes():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        (Path(home) / ".hermit").mkdir()
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "~/.hermit dir")
        assert chk.status == DiagStatus.PASS


def test_hooks_json_invalid_fails():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        hermit_agent_dir = Path(home) / ".hermit"
        hermit_agent_dir.mkdir()
        (hermit_agent_dir / "hooks.json").write_text("{not valid json")
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "hooks.json")
        assert chk.status == DiagStatus.FAIL


def test_hooks_json_valid_passes():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        hermit_agent_dir = Path(home) / ".hermit"
        hermit_agent_dir.mkdir()
        (hermit_agent_dir / "hooks.json").write_text(json.dumps({"hooks": []}))
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "hooks.json")
        assert chk.status == DiagStatus.PASS


def test_hooks_json_absent_passes():
    """Missing hooks.json is normal — having no hooks is also a valid state."""
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        (Path(home) / ".hermit").mkdir()
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "hooks.json")
        assert chk.status == DiagStatus.PASS


def test_permissions_sensitive_deny_active():
    """The sensitive file deny floor added in Priority 1 must be enabled."""
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "permissions.sensitive_deny")
        assert chk.status == DiagStatus.PASS


def test_hermes_mcp_missing_cli_warns(monkeypatch):
    import hermit_agent.doctor as doctor_mod

    monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: None if name == "hermes" else "/bin/tool")

    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "Hermes MCP")
        assert chk.status == DiagStatus.WARN
        assert "hermes command not found" in chk.message
        assert "--print-hermes-mcp-config" in chk.message


def test_hermes_mcp_registered_passes(monkeypatch):
    import hermit_agent.doctor as doctor_mod

    class Result:
        returncode = 0
        stdout = json.dumps({"servers": {"hermit-channel": {"command": "hermit", "args": ["mcp-server"]}}})
        stderr = ""

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: "/usr/local/bin/hermes" if name == "hermes" else None)
    monkeypatch.setattr(
        doctor_mod.subprocess,
        "run",
        lambda args, **kwargs: calls.append({"args": args, "env": kwargs.get("env")}) or Result(),
    )

    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        hermes_home = Path(home) / ".hermes-isolated"
        report = run_diagnostics(cwd=project, home=home, hermes_home=str(hermes_home))
        chk = next(c for c in report.checks if c.name == "Hermes MCP")
        assert chk.status == DiagStatus.PASS
        assert "hermit-channel registered" in chk.message
        assert calls == [{"args": ["hermes", "mcp", "list", "--json"], "env": {**__import__("os").environ, "HERMES_HOME": str(hermes_home)}}]


def test_hermes_mcp_list_falls_back_when_json_flag_is_unsupported(monkeypatch):
    import hermit_agent.doctor as doctor_mod

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["hermes", "mcp", "list", "--json"]:
            return Result(2, stderr="hermes: error: unrecognized arguments: --json")
        if args == ["hermes", "mcp", "list"]:
            return Result(0, stdout="hermit-channel\n  command: hermit\n  args: mcp-server\n")
        raise AssertionError(args)

    monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: "/usr/local/bin/hermes" if name == "hermes" else None)
    monkeypatch.setattr(doctor_mod.subprocess, "run", fake_run)

    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "Hermes MCP")
        assert chk.status == DiagStatus.PASS
        assert "hermit-channel registered" in chk.message
        assert calls == [["hermes", "mcp", "list", "--json"], ["hermes", "mcp", "list"]]


def test_hermes_mcp_subprocess_error_warns(monkeypatch):
    import hermit_agent.doctor as doctor_mod

    monkeypatch.setattr(doctor_mod.shutil, "which", lambda name: "/usr/local/bin/hermes" if name == "hermes" else None)
    monkeypatch.setattr(doctor_mod.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cwd missing")))

    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        chk = next(c for c in report.checks if c.name == "Hermes MCP")
        assert chk.status == DiagStatus.WARN
        assert "unable to inspect Hermes MCP servers" in chk.message


def test_overall_status_fail_when_any_fail():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        hermit_agent_dir = Path(home) / ".hermit"
        hermit_agent_dir.mkdir()
        (hermit_agent_dir / "hooks.json").write_text("{broken")
        report = run_diagnostics(cwd=project, home=home)
        assert report.overall == DiagStatus.FAIL


def test_format_report_produces_string():
    with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
        report = run_diagnostics(cwd=project, home=home)
        text = report.format()
        assert "HERMIT.md" in text
        assert isinstance(text, str) and len(text) > 0
