#!/usr/bin/env python3
"""Fail release builds when public packages contain retired product surfaces."""

from __future__ import annotations

import argparse
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
RETIRED_PATH_PARTS = (
    "hermit-ui/",
    "hermit_agent/bridge",
    "hermit_agent/loop_commands/",
    "hermit_agent/interfaces/",
    "hermit_agent/orchestrators/",
    "hermit_agent/sinks/",
    "hermit_agent/guardrails/",
    "hermit_agent/metrics/",
    "hermit_agent/mcp/",
)
NPM_PUBLIC_FILES = {"LICENSE", "README.md", "bin/hermit.js", "package.json"}


def archive_members(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return set(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return {member.name for member in archive.getmembers() if member.isfile()}
    raise ValueError(f"Unsupported artifact: {path}")


def _without_sdist_root(members: Iterable[str]) -> set[str]:
    cleaned: set[str] = set()
    for member in members:
        _, separator, relative = member.partition("/")
        cleaned.add(relative if separator else member)
    return cleaned


def assert_no_retired_paths(members: Iterable[str], *, artifact: Path) -> None:
    retired = sorted(member for member in members if any(part in member for part in RETIRED_PATH_PARTS))
    if retired:
        raise ValueError(f"{artifact} includes retired paths: {', '.join(retired)}")


def verify_python_distributions(*, dist_dir: Path, version: str) -> None:
    package_stem = f"cafitac_hermit_agent-{version}"
    wheel = dist_dir / f"{package_stem}-py3-none-any.whl"
    sdist = dist_dir / f"{package_stem}.tar.gz"
    for artifact in (wheel, sdist):
        if not artifact.is_file():
            raise FileNotFoundError(f"Expected release artifact is missing: {artifact}")
        members = archive_members(artifact)
        assert_no_retired_paths(members, artifact=artifact)
        normalized = members if artifact.suffix == ".whl" else _without_sdist_root(members)
        if "hermit_agent/mcp_server.py" not in normalized:
            raise ValueError(f"{artifact} does not contain the Hermit MCP server")
        if artifact.name.endswith(".tar.gz") and any(member.startswith("tests/") for member in normalized):
            raise ValueError(f"{artifact} includes development tests")


def npm_package_files(*, npm_command: str = "npm") -> set[str]:
    completed = subprocess.run(
        [npm_command, "pack", "--dry-run", "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("npm pack did not return exactly one package")
    files = payload[0].get("files", [])
    return {str(item["path"]) for item in files if isinstance(item, dict) and "path" in item}


def verify_npm_distribution(*, npm_command: str = "npm") -> None:
    files = npm_package_files(npm_command=npm_command)
    if files != NPM_PUBLIC_FILES:
        raise ValueError(f"npm package files differ from the minimal launcher: {sorted(files)}")
    assert_no_retired_paths(files, artifact=Path("npm package"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--npm-command", default="npm")
    args = parser.parse_args(argv)

    verify_python_distributions(dist_dir=args.dist_dir, version=args.version)
    verify_npm_distribution(npm_command=args.npm_command)
    print(f"Release artifacts verified for {args.version}.")


if __name__ == "__main__":
    main()
