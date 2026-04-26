from __future__ import annotations

import os
import stat
import subprocess
import json
from pathlib import Path


def _write_fake_npm(path: Path, *, listed_version: str) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ \"$1\" = \"install\" ]; then',
                "  exit 0",
                "fi",
                'if [ \"$1\" = \"list\" ]; then',
                f"  printf '%s' '{{\"dependencies\":{{\"@cafitac/hermit-agent\":{{\"version\":\"{listed_version}\"}}}}}}'",
                "  exit 0",
                "fi",
                'if [ \"$1\" = \"view\" ]; then',
                f"  printf '%s' '\"{listed_version}\"'",
                "  exit 0",
                "fi",
                "echo unexpected npm invocation >&2",
                "exit 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _current_version() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    package_json = repo_root / "hermit-ui" / "package.json"
    payload = json.loads(package_json.read_text(encoding="utf-8"))
    return str(payload["version"])


def _next_patch(version: str) -> str:
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def _run_hermit_update(*, listed_version: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    hermit_script = repo_root / "hermit-ui" / "bin" / "hermit.js"

    temp_dir = repo_root / ".pytest-hermit-update-bin"
    temp_dir.mkdir(exist_ok=True)
    fake_npm = temp_dir / "npm"
    _write_fake_npm(fake_npm, listed_version=listed_version)

    env = dict(os.environ)
    env["PATH"] = f"{temp_dir}:{env.get('PATH', '')}"
    env["HERMIT_SKIP_MANAGED_RUNTIME_SYNC"] = "1"

    try:
        return subprocess.run(
            ["node", str(hermit_script), "update"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_npm.unlink(missing_ok=True)
        temp_dir.rmdir()


def test_hermit_update_reports_version_upgrade():
    current = _current_version()
    upgraded = _next_patch(current)
    result = _run_hermit_update(listed_version=upgraded)

    assert result.returncode == 0
    assert f"[hermit] Updated from v{current} to v{upgraded}." in result.stdout


def test_hermit_update_reports_already_latest():
    current = _current_version()
    result = _run_hermit_update(listed_version=current)

    assert result.returncode == 0
    assert f"[hermit] Already using the latest version (v{current})." in result.stdout


def test_hermit_no_arg_prompt_can_trigger_update():
    repo_root = Path(__file__).resolve().parents[1]
    hermit_script = repo_root / "hermit-ui" / "bin" / "hermit.js"

    temp_dir = repo_root / ".pytest-hermit-update-bin"
    temp_dir.mkdir(exist_ok=True)
    fake_npm = temp_dir / "npm"
    current = _current_version()
    upgraded = _next_patch(current)
    _write_fake_npm(fake_npm, listed_version=upgraded)

    env = dict(os.environ)
    env["PATH"] = f"{temp_dir}:{env.get('PATH', '')}"
    env["HERMIT_FORCE_STARTUP_PROMPTS"] = "1"
    env["HERMIT_SKIP_MANAGED_RUNTIME_SYNC"] = "1"

    try:
        result = subprocess.run(
            ["node", str(hermit_script)],
            cwd=repo_root,
            env=env,
            input="y\n",
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_npm.unlink(missing_ok=True)
        temp_dir.rmdir()

    assert result.returncode == 0
    assert "Update before continuing?" in result.stdout
    assert f"[hermit] Updated from v{current} to v{upgraded}." in result.stdout


def test_hermit_status_prompt_can_trigger_update():
    repo_root = Path(__file__).resolve().parents[1]
    hermit_script = repo_root / "hermit-ui" / "bin" / "hermit.js"

    temp_dir = repo_root / ".pytest-hermit-update-bin"
    temp_dir.mkdir(exist_ok=True)
    fake_npm = temp_dir / "npm"
    current = _current_version()
    upgraded = _next_patch(current)
    _write_fake_npm(fake_npm, listed_version=upgraded)

    env = dict(os.environ)
    env["PATH"] = f"{temp_dir}:{env.get('PATH', '')}"
    env["HERMIT_FORCE_STARTUP_PROMPTS"] = "1"
    env["HERMIT_SKIP_MANAGED_RUNTIME_SYNC"] = "1"

    try:
        result = subprocess.run(
            ["node", str(hermit_script), "status"],
            cwd=repo_root,
            env=env,
            input="y\n",
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_npm.unlink(missing_ok=True)
        temp_dir.rmdir()

    assert result.returncode == 0
    assert "Update before continuing?" in result.stdout
    assert f"[hermit] Updated from v{current} to v{upgraded}." in result.stdout


def test_hermit_help_skips_startup_update_prompt():
    repo_root = Path(__file__).resolve().parents[1]
    hermit_script = repo_root / "hermit-ui" / "bin" / "hermit.js"

    temp_dir = repo_root / ".pytest-hermit-update-bin"
    temp_dir.mkdir(exist_ok=True)
    fake_npm = temp_dir / "npm"
    current = _current_version()
    upgraded = _next_patch(current)
    _write_fake_npm(fake_npm, listed_version=upgraded)

    env = dict(os.environ)
    env["PATH"] = f"{temp_dir}:{env.get('PATH', '')}"
    env["HERMIT_FORCE_STARTUP_PROMPTS"] = "1"
    env["HERMIT_SKIP_MANAGED_RUNTIME_SYNC"] = "1"

    try:
        result = subprocess.run(
            ["node", str(hermit_script), "help"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_npm.unlink(missing_ok=True)
        temp_dir.rmdir()

    assert result.returncode == 0
    assert "Update before continuing?" not in result.stdout
    assert "Show this help message" in result.stdout


def test_hermit_subcommand_syncs_managed_runtime_before_running_backend(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    hermit_script = repo_root / "hermit-ui" / "bin" / "hermit.js"

    fake_home = tmp_path / "home"
    venv_bin = fake_home / ".hermit" / "npm-runtime" / "venv" / "bin"
    venv_bin.mkdir(parents=True)

    fake_python = venv_bin / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ \"$1\" = \"-c\" ]; then',
                "  printf '%s\\n' '0.3.19'",
                "  exit 0",
                "fi",
                "exit 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    fake_python3 = venv_bin / "python3"
    fake_python3.write_text(fake_python.read_text(encoding="utf-8"), encoding="utf-8")
    fake_python3.chmod(fake_python3.stat().st_mode | stat.S_IXUSR)

    fake_pip = venv_bin / "pip"
    fake_pip.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "echo \"$@\" > \"$HERMIT_TEST_SYNC_LOG\"",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_pip.chmod(fake_pip.stat().st_mode | stat.S_IXUSR)

    fake_hermit = venv_bin / "hermit"
    fake_hermit.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "echo \"backend:$@\"",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_hermit.chmod(fake_hermit.stat().st_mode | stat.S_IXUSR)

    sync_log = tmp_path / "sync.log"
    env = dict(os.environ)
    env["HERMIT_HOME"] = str(fake_home)
    env["HERMIT_TEST_SYNC_LOG"] = str(sync_log)
    env["HERMIT_SKIP_STARTUP_UPDATE_CHECK"] = "1"

    result = subprocess.run(
        ["node", str(hermit_script), "status"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[hermit] Syncing managed runtime to" in result.stdout
    assert "backend:status" in result.stdout
    assert "install --quiet --upgrade cafitac-hermit-agent==" in sync_log.read_text(encoding="utf-8")
