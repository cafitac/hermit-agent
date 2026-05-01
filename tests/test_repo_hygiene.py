from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_ignore(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def test_refactor_planning_docs_are_trackable_but_other_dev_files_stay_ignored():
    """Long-term refactor plans are intentional project docs, unlike local .dev scratch files."""
    assert _check_ignore(".dev/refactor/README.md").returncode == 1
    assert _check_ignore(".dev/refactor/roadmap.md").returncode == 1
    assert _check_ignore(".dev/scratch.md").returncode == 0
