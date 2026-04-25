from __future__ import annotations

import os
from pathlib import Path


DEFAULT_TEXT_LOG_MAX_BYTES = int(os.environ.get("HERMIT_TEXT_LOG_MAX_BYTES", str(2 * 1024 * 1024)))
DEFAULT_TEXT_LOG_BACKUPS = int(os.environ.get("HERMIT_TEXT_LOG_BACKUPS", "5"))
DEFAULT_JSONL_LOG_MAX_BYTES = int(os.environ.get("HERMIT_JSONL_LOG_MAX_BYTES", str(4 * 1024 * 1024)))
DEFAULT_JSONL_LOG_BACKUPS = int(os.environ.get("HERMIT_JSONL_LOG_BACKUPS", "3"))
DEFAULT_SESSION_MAX_KEEP = int(os.environ.get("HERMIT_SESSION_MAX_KEEP", "200"))
DEFAULT_METRICS_MAX_KEEP = int(os.environ.get("HERMIT_METRICS_MAX_KEEP", "500"))

_created_dirs: set[str] = set()


def _ensure_dir(directory: str) -> None:
    if directory and directory not in _created_dirs:
        os.makedirs(directory, exist_ok=True)
        _created_dirs.add(directory)


def rotate_text_log(path: str, *, max_bytes: int = DEFAULT_TEXT_LOG_MAX_BYTES, backups: int = DEFAULT_TEXT_LOG_BACKUPS) -> None:
    """Rotate a plain append-only text log in-place when it exceeds max_bytes."""
    if max_bytes <= 0 or backups <= 0:
        return
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) < max_bytes:
            return

        oldest = f"{path}.{backups}"
        if os.path.exists(oldest):
            os.remove(oldest)

        for idx in range(backups - 1, 0, -1):
            src = f"{path}.{idx}"
            dst = f"{path}.{idx + 1}"
            if os.path.exists(src):
                os.replace(src, dst)

        os.replace(path, f"{path}.1")
    except OSError:
        return


def append_text_log(path: str, line: str, *, max_bytes: int = DEFAULT_TEXT_LOG_MAX_BYTES, backups: int = DEFAULT_TEXT_LOG_BACKUPS) -> None:
    """Append one line to a rotating plain-text log file."""
    _ensure_dir(os.path.dirname(path))
    rotate_text_log(path, max_bytes=max_bytes, backups=backups)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


def append_jsonl_record(
    path: str,
    line: str,
    *,
    max_bytes: int | None = None,
    backups: int | None = None,
) -> None:
    """Append one JSONL record to a rotating file."""
    resolved_max_bytes = DEFAULT_JSONL_LOG_MAX_BYTES if max_bytes is None else max_bytes
    resolved_backups = DEFAULT_JSONL_LOG_BACKUPS if backups is None else backups
    _ensure_dir(os.path.dirname(path))
    rotate_text_log(path, max_bytes=resolved_max_bytes, backups=resolved_backups)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


def prune_oldest_files(directory: str | Path, *, pattern: str, max_keep: int) -> None:
    """Delete oldest matching files until at most max_keep remain."""
    if max_keep <= 0:
        return
    root = Path(directory)
    if not root.exists():
        return
    files = sorted(
        (p for p in root.glob(pattern) if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    excess = len(files) - max_keep
    for path in files[:excess] if excess > 0 else []:
        try:
            path.unlink()
        except OSError:
            continue
