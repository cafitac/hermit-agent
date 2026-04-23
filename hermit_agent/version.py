from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import re

PACKAGE_NAME = "cafitac-hermit-agent"
VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


def _read_repo_version() -> str | None:
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        match = VERSION_RE.search(pyproject_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return match.group(1) if match else None


def get_version() -> str:
    repo_version = _read_repo_version()
    if repo_version:
        return repo_version
    try:
        return package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


VERSION = get_version()
