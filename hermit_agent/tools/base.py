"""Tool base interface and shared helpers.

This module is the dependency base for other tool_*.py files and imports nothing outside stdlib.
To prevent circular imports, never do `from .tools import ...` here.
"""

from __future__ import annotations

import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


# ─── Result structures ─────────────────────────

@dataclass
class ToolResult:
    content: str
    is_error: bool = False


# ─── Secret detection ─────────────────────────

_SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+',
    r'(?i)(secret|password|passwd|token)\s*[=:]\s*\S+',
    r'(?i)(aws_access_key_id|aws_secret_access_key)\s*=\s*\S+',
    r'AKIA[0-9A-Z]{16}',
    r'ghp_[a-zA-Z0-9]{36}',
    r'sk-[a-zA-Z0-9]{48}',
]


def _check_secrets(content: str) -> list[str]:
    """Check content for potential secrets."""
    warnings = []
    for pattern in _SECRET_PATTERNS:
        if re.search(pattern, content):
            warnings.append(f"Potential secret detected: {pattern[:30]}...")
    return warnings


# ─── Path utilities ─────────────────────────

def _is_safe_path(path: str, cwd: str = ".") -> str | None:
    """Check for symlink attacks and path traversal. Returns error message or None."""
    real_path = os.path.realpath(path)
    allowed_roots = _allowed_path_roots(cwd)
    if not any(_path_is_within(real_path, root) for root in allowed_roots):
        return (
            f"Path traversal blocked: {path} resolves to {real_path} outside allowed directories "
            f"(cwd, temp, and managed config dirs only)"
        )
    return None


def _allowed_path_roots(cwd: str) -> list[str]:
    home = os.path.realpath(os.path.expanduser("~"))
    roots = [
        os.path.realpath(cwd),
        os.path.realpath("/tmp"),
        os.path.realpath(tempfile.gettempdir()),  # macOS: /var/folders → /private/var/folders
    ]
    roots.extend(
        os.path.join(home, subdir)
        for subdir in (".hermit", ".claude", ".codex")
    )
    return roots


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def _expand_path(path: str, cwd: str = ".") -> str:
    """Expand ~ and resolve relative paths to absolute. Claude Code's expandPath pattern."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return os.path.normpath(path)


def _display_path(path: str, cwd: str) -> str:
    """G40: Convert absolute path to relative path based on cwd (only when inside cwd). Keep absolute if outside."""
    try:
        abs_path = os.path.abspath(path)
        abs_cwd = os.path.abspath(cwd)
        if abs_path.startswith(abs_cwd + os.sep) or abs_path == abs_cwd:
            return os.path.relpath(abs_path, abs_cwd)
    except Exception:
        pass
    return path


def _format_content_preview(content: str, max_lines: int = 10) -> str:
    """G40: Content preview to attach to write_file results (line numbers + truncation notice)."""
    lines = content.splitlines()
    total = len(lines)
    if total == 0:
        return "(empty file)"
    width = len(str(min(total, max_lines)))
    shown = lines[:max_lines]
    body = "\n".join(f"{str(i + 1).rjust(width)}\t{line}" for i, line in enumerate(shown))
    if total > max_lines:
        body += f"\n... +{total - max_lines} more lines"
    return body


def _redirect_to_worktree_path(path: str, cwd: str) -> tuple[str, str]:
    """G39: When working in a worktree, redirect main repo absolute paths to the worktree equivalent.

    Conditions (all must be met for redirect):
      1. cwd is inside a worktree (under `.worktrees/<branch>`)
      2. path is outside cwd but under the worktree's parent repo root
      3. The corresponding file exists in the worktree (only when file exists in both)

    Returns: (redirected_path, notice_text)
      Empty notice_text means no redirect.
    """
    try:
        if not os.path.isabs(path):
            return path, ""
        cwd_abs = os.path.abspath(cwd)
        path_abs = os.path.abspath(path)
        # Detect worktree: cwd path must contain /.worktrees/ segment
        marker = os.sep + ".worktrees" + os.sep
        idx = cwd_abs.find(marker)
        if idx < 0:
            return path, ""
        main_root = cwd_abs[:idx]
        # If path is not under main_root (editing an external path — legit), skip redirect
        if not path_abs.startswith(main_root + os.sep):
            return path, ""
        # Already inside cwd — use as-is
        if path_abs.startswith(cwd_abs + os.sep):
            return path, ""
        # If pointing to a different worktree (.worktrees/other-branch/), don't touch
        post_main = path_abs[len(main_root):]
        if post_main.startswith(marker):
            return path, ""
        # Compute relative path and generate candidate path inside worktree
        rel = os.path.relpath(path_abs, main_root)
        candidate = os.path.normpath(os.path.join(cwd_abs, rel))
        # Only redirect if the corresponding file exists in the worktree
        if not os.path.exists(candidate):
            return path, ""
        notice = (
            f"[G39 path redirect] working in worktree, "
            f"redirecting {path_abs} → {candidate}"
        )
        return candidate, notice
    except Exception:
        return path, ""


# ─── Tool interface ─────────────────────────

class Tool(ABC):
    """Base tool interface. Based on Claude Code's buildTool() pattern."""

    name: str
    description: str
    _agent: Any = None  # set by AgentLoop; Any avoids circular import with loop.py

    @abstractmethod
    def input_schema(self) -> dict:
        ...

    @abstractmethod
    def execute(self, input: dict) -> ToolResult:
        ...

    def validate(self, input: dict) -> str | None:
        """Input validation. Returns an error message or None."""
        return None

    @property
    def is_read_only(self) -> bool:
        return False

    @property
    def is_concurrent_safe(self) -> bool:
        return False

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }


__all__ = [
    "Tool",
    "ToolResult",
    "_check_secrets",
    "_is_safe_path",
    "_expand_path",
    "_display_path",
    "_format_content_preview",
    "_redirect_to_worktree_path",
]
