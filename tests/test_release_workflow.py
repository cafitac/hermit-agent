from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_requires_explicit_approval_and_builds_all_public_artifacts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/publish-npm.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "confirm_publish:" in workflow
    assert "push:" not in workflow
    assert "python scripts/build_mcpb.py" in workflow
    assert "python scripts/verify_release_artifacts.py" in workflow
    assert "python -m build --outdir dist/python" in workflow
    assert "npm publish --access public --provenance" in workflow
    assert "gh-action-pypi-publish" in workflow
    assert "packages-dir: dist/python" in workflow
    assert "dist/*.mcpb dist/python/*" in workflow


def test_legacy_duplicate_release_workflows_are_removed() -> None:
    workflows = REPO_ROOT / ".github/workflows"

    assert not (workflows / "publish-github-release.yml").exists()
    assert not (workflows / "publish-pypi.yml").exists()


def test_release_notes_renderer_does_not_depend_on_retired_docs(tmp_path: Path) -> None:
    output = tmp_path / "notes.md"

    subprocess.run(
        [
            sys.executable,
            "scripts/render_release_notes.py",
            "--tag",
            "v0.4.0",
            "--version",
            "0.4.0",
            "--repo",
            "cafitac/hermit-agent",
            "--out",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    notes = output.read_text(encoding="utf-8")
    assert "## Summary" in notes
    assert "@cafitac/hermit-agent@0.4.0" in notes
