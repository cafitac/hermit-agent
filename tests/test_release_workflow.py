from __future__ import annotations

import subprocess
import sys
import tomllib
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
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]

    subprocess.run(
        [
            sys.executable,
            "scripts/render_release_notes.py",
            "--tag",
            f"v{version}",
            "--version",
            version,
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
    assert f"@cafitac/hermit-agent@{version}" in notes


def test_release_metadata_versions_are_aligned() -> None:
    import json

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    manifest = json.loads((REPO_ROOT / "mcpb/manifest.json").read_text(encoding="utf-8"))
    mcpb_pyproject = (REPO_ROOT / "mcpb/pyproject.toml").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert package["version"] == version
    assert manifest["version"] == version
    assert f'version = "{version}"' in mcpb_pyproject
    assert f"cafitac-hermit-agent=={version}" in mcpb_pyproject
    assert f"## v{version}" in changelog
