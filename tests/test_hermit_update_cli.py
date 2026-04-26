from __future__ import annotations

import os
import stat
import subprocess
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
                "echo unexpected npm invocation >&2",
                "exit 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_hermit_update(*, listed_version: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    hermit_script = repo_root / "hermit-ui" / "bin" / "hermit.js"

    temp_dir = repo_root / ".pytest-hermit-update-bin"
    temp_dir.mkdir(exist_ok=True)
    fake_npm = temp_dir / "npm"
    _write_fake_npm(fake_npm, listed_version=listed_version)

    env = dict(os.environ)
    env["PATH"] = f"{temp_dir}:{env.get('PATH', '')}"

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
    result = _run_hermit_update(listed_version="0.3.20")

    assert result.returncode == 0
    assert "[hermit] Updated from v0.3.19 to v0.3.20." in result.stdout


def test_hermit_update_reports_already_latest():
    result = _run_hermit_update(listed_version="0.3.19")

    assert result.returncode == 0
    assert "[hermit] Already using the latest version (v0.3.19)." in result.stdout
