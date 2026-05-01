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


def test_developer_docs_use_python_module_pytest_entrypoint():
    """The repo-local pytest script can have a stale shebang; docs should use python -m pytest."""
    docs = {
        path: (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "CONTRIBUTING.md", "CLAUDE.md", "HERMIT.md")
    }

    forbidden_command_prefixes = (
        ".venv/bin/pytest",
        "pytest tests/",
        "pytest   ",
    )

    offending_docs = {
        path: line.strip()
        for path, content in docs.items()
        for line in content.splitlines()
        if line.strip().startswith(forbidden_command_prefixes)
    }

    assert offending_docs == {}
