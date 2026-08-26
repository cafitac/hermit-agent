#!/usr/bin/env python3
"""Build a version-aligned Claude Desktop MCPB artifact for Hermit."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MCPB_SOURCE = REPO_ROOT / "mcpb"
REQUIRED_MEMBERS = {"manifest.json", "pyproject.toml", "server.py"}
MCPB_CLI = ("npx", "--yes", "@anthropic-ai/mcpb@2.1.2")


def project_version(project_file: Path = REPO_ROOT / "pyproject.toml") -> str:
    with project_file.open("rb") as handle:
        payload = tomllib.load(handle)
    version = str(payload["project"]["version"])
    if not version:
        raise ValueError("Project version is required for MCPB packaging.")
    return version


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _render_pyproject(version: str) -> str:
    return "\n".join(
        (
            "[project]",
            'name = "hermit-desktop-extension"',
            f'version = "{version}"',
            'description = "Claude Desktop MCPB launcher for Hermit"',
            'requires-python = ">=3.11"',
            "dependencies = [",
            f'    "cafitac-hermit-agent=={version}",',
            "]",
            "",
        )
    )


def prepare_bundle_directory(destination: Path, *, version: str) -> Path:
    """Copy the small MCPB launcher and align all package versions."""
    destination.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(MCPB_SOURCE / "manifest.json")
    manifest["version"] = version
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (destination / "pyproject.toml").write_text(_render_pyproject(version), encoding="utf-8")
    for name in ("server.py", ".mcpbignore"):
        shutil.copy2(MCPB_SOURCE / name, destination / name)
    return destination


def validate_bundle_structure(bundle_path: Path, *, version: str) -> None:
    with zipfile.ZipFile(bundle_path) as archive:
        members = set(archive.namelist())
        missing = REQUIRED_MEMBERS - members
        if missing:
            raise ValueError(f"MCPB archive is missing: {', '.join(sorted(missing))}")
        manifest = json.loads(archive.read("manifest.json"))
        pyproject = tomllib.loads(archive.read("pyproject.toml").decode("utf-8"))

    if manifest.get("manifest_version") != "0.4" or manifest.get("server", {}).get("type") != "uv":
        raise ValueError("MCPB must use the UV runtime manifest contract.")
    if manifest.get("version") != version or pyproject["project"]["version"] != version:
        raise ValueError("MCPB artifact versions do not match the release version.")
    dependencies = pyproject["project"].get("dependencies", [])
    if f"cafitac-hermit-agent=={version}" not in dependencies:
        raise ValueError("MCPB must install the matching Hermit PyPI package.")


def build_mcpb(*, output: Path, version: str, mcpb_cli: tuple[str, ...] = MCPB_CLI) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hermit-mcpb-") as temporary:
        bundle_dir = prepare_bundle_directory(Path(temporary) / "hermit", version=version)
        subprocess.run([*mcpb_cli, "validate", str(bundle_dir / "manifest.json")], check=True)
        subprocess.run([*mcpb_cli, "pack", str(bundle_dir), str(output)], check=True)
    validate_bundle_structure(output, version=version)
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build Hermit's Claude Desktop MCPB artifact.")
    parser.add_argument("--version", default=project_version(), help="Release version to embed in the artifact")
    parser.add_argument("--output", type=Path, help="Output path (default: dist/hermit-<version>.mcpb)")
    args = parser.parse_args(argv)
    output = args.output or REPO_ROOT / "dist" / f"hermit-{args.version}.mcpb"
    print(build_mcpb(output=output, version=args.version))


if __name__ == "__main__":
    main()
