"""Tests for install.sh US-008: settings rename detection and --dry-run flag.

AC:
- When ~/.hermit/settings.json contains a non-empty llm_api_key and
  gateway.db does not exist (no migration 002 applied), install.sh
  with --dry-run prints a message containing "please review" (case-insensitive).
- When ~/.hermit/ does not exist at all (fresh install), "please review"
  does NOT appear.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).parent.parent


def _run_install(tmpdir: str, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run install.sh with a temporary HOME to avoid touching the real system."""
    args = extra_args or []
    env = os.environ.copy()
    env["HOME"] = tmpdir
    env["PROJECT_DIR"] = str(PROJECT_DIR)
    # Prevent interactive prompts from blocking: point SHELL to something stable
    env["SHELL"] = "/bin/bash"
    result = subprocess.run(
        ["bash", str(PROJECT_DIR / "install.sh"), "--dry-run"] + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return result


def test_settings_rename_detection():
    """Stale llm_api_key in settings.json triggers the rename warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hermit_dir = Path(tmpdir) / ".hermit"
        hermit_dir.mkdir(parents=True)
        settings = {
            "llm_api_key": "some-old-value",
            "gateway_url": "http://localhost:8765",
        }
        (hermit_dir / "settings.json").write_text(json.dumps(settings, indent=2))

        result = _run_install(tmpdir)
        combined = (result.stdout + result.stderr).lower()
        assert "please review" in combined, (
            f"Expected 'please review' in output.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def test_settings_rename_absent_when_fresh_install():
    """Fresh install with no ~/.hermit/ must NOT trigger the rename warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # No ~/.hermit/ directory at all
        result = _run_install(tmpdir)
        combined = (result.stdout + result.stderr).lower()
        assert "please review" not in combined, (
            f"Did not expect 'please review' in fresh-install output.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
