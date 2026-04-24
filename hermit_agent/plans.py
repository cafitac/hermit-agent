"""Save/List/Load Plan artifacts (`.hermit/plans/`).

Saves plans created in Plan mode to disk for later reference.
Filename format: `{YYYYMMDD-HHMMSS}_{slug}.md`
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_PLAN_DIR_NAME = os.path.join(".hermit", "plans")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class PlanInfo:
    name: str
    path: Path
    mtime: float
    size_chars: int


def _plans_dir(cwd: str) -> Path:
    return Path(cwd) / _PLAN_DIR_NAME


def _sanitize(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", name).strip("-")
    return cleaned or "plan"


def save_plan(content: str, name: str | None = None, cwd: str | None = None) -> Path:
    cwd = cwd or os.getcwd()
    plans_dir = _plans_dir(cwd)
    plans_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _sanitize(name) if name else "plan"
    filename = f"{ts}_{slug}.md"
    path = plans_dir / filename
    path.write_text(content)
    return path


def load_plan(name: str, cwd: str | None = None) -> str:
    cwd = cwd or os.getcwd()
    plans_dir = _plans_dir(cwd)
    if not plans_dir.is_dir():
        raise FileNotFoundError(f"No plans directory: {plans_dir}")

    direct = plans_dir / name
    if direct.is_file():
        return direct.read_text()

    for path in plans_dir.glob("*.md"):
        if name in path.name or name == path.stem:
            return path.read_text()

    raise FileNotFoundError(f"No plan matching '{name}' in {plans_dir}")


def list_plans(cwd: str | None = None) -> list[PlanInfo]:
    cwd = cwd or os.getcwd()
    plans_dir = _plans_dir(cwd)
    if not plans_dir.is_dir():
        return []

    entries: list[PlanInfo] = []
    for path in plans_dir.glob("*.md"):
        stat = path.stat()
        entries.append(
            PlanInfo(
                name=path.stem,
                path=path,
                mtime=stat.st_mtime,
                size_chars=stat.st_size,
            )
        )
    entries.sort(key=lambda p: p.mtime, reverse=True)
    return entries
