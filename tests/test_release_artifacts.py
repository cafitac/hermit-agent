from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_release_artifacts import (
    NPM_PUBLIC_FILES,
    assert_no_retired_paths,
    npm_package_files,
    verify_python_distributions,
)


def _write_python_distributions(
    dist_dir: Path, version: str, *, retired: bool = False, include_tests: bool = False
) -> None:
    stem = f"cafitac_hermit_agent-{version}"
    wheel = dist_dir / f"{stem}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("hermit_agent/mcp_server.py", "")
        if retired:
            archive.writestr("hermit_agent/bridge/core.py", "")

    sdist = dist_dir / f"{stem}.tar.gz"
    source = dist_dir / "source.py"
    source.write_text("", encoding="utf-8")
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(source, arcname=f"{stem}/hermit_agent/mcp_server.py")
        if include_tests:
            archive.add(source, arcname=f"{stem}/tests/test_legacy.py")


def test_verify_python_distributions_accepts_the_minimal_mcp_runtime(tmp_path: Path) -> None:
    _write_python_distributions(tmp_path, "0.4.0")

    verify_python_distributions(dist_dir=tmp_path, version="0.4.0")


def test_verify_python_distributions_rejects_retired_paths(tmp_path: Path) -> None:
    _write_python_distributions(tmp_path, "0.4.0", retired=True)

    with pytest.raises(ValueError, match="retired paths"):
        verify_python_distributions(dist_dir=tmp_path, version="0.4.0")


def test_verify_python_distributions_rejects_development_tests_in_the_sdist(tmp_path: Path) -> None:
    _write_python_distributions(tmp_path, "0.4.0", include_tests=True)

    with pytest.raises(ValueError, match="development tests"):
        verify_python_distributions(dist_dir=tmp_path, version="0.4.0")


def test_npm_dry_run_lists_only_the_minimal_launcher_package() -> None:
    assert npm_package_files() == NPM_PUBLIC_FILES


def test_retired_path_check_reports_the_public_artifact() -> None:
    with pytest.raises(ValueError, match="npm package"):
        assert_no_retired_paths({"hermit-ui/dist/app.js"}, artifact=Path("npm package"))
