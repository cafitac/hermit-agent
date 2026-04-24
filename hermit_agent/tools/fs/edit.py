"""EditFileTool implementation."""

from __future__ import annotations

import glob
import os
import re

from ..base import (
    Tool,
    ToolResult,
    _check_secrets,
    _expand_path,
    _is_safe_path,
    _redirect_to_worktree_path,
)
from .read import ReadFileTool


def _shorten_path(path: str, max_len: int = 80) -> str:
    """Shorten long paths with `...` in the middle. Shortens the middle to preserve the filename (§28)."""
    try:
        cwd = os.getcwd()
        if path.startswith(cwd + os.sep):
            path = os.path.relpath(path, cwd)
    except Exception:
        pass
    if len(path) <= max_len:
        return path
    keep = max_len - 3  # 3 for "..."
    head = keep // 2
    tail = keep - head
    return path[:head] + "..." + path[-tail:]


def _format_edit_diff(path: str, old_string: str, new_string: str, start_line: int) -> str:
    """unified_diff based edit diff format (§28 G24).

    - Changed lines only: `-`/`+`
    - Unchanged context: space prefix
    - hunk header `@@ -N,M +N,M @@` preserved
    """
    import difflib

    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()

    display_path = _shorten_path(path)

    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        lineterm="",
        n=3,
    ))

    # The first 2 lines of unified_diff are `--- ` / `+++ ` headers — discard and use hunks only.
    hunks = [line for line in diff_lines if not (line.startswith("--- ") or line.startswith("+++ "))]

    # Adjust hunk header start line number to actual file position (start_line)
    rebased: list[str] = []
    for line in hunks:
        if line.startswith("@@"):
            # @@ -1,3 +1,5 @@  → -<start_line>,M +<start_line>,M
            m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                old_off = int(m.group(1))
                old_count = int(m.group(2) or 1)
                new_off = int(m.group(3))
                new_count = int(m.group(4) or 1)
                # 1-based: start row = start_line + (off - 1)
                new_old = start_line + (old_off - 1)
                new_new = start_line + (new_off - 1)
                rebased.append(f"@@ -{new_old},{old_count} +{new_new},{new_count} @@")
            else:
                rebased.append(line)
        else:
            rebased.append(line)

    removed = sum(1 for line in rebased if line.startswith("-") and not line.startswith("---"))
    added = sum(1 for line in rebased if line.startswith("+") and not line.startswith("+++"))

    parts = [f"Update({display_path})"]
    if added > removed:
        parts.append(f"  +{added - removed} lines")
    elif removed > added:
        parts.append(f"  -{removed - added} lines")
    else:
        parts.append(f"  ~{added} lines")
    parts.extend("  " + line for line in rebased)
    return "\n".join(parts)


class EditFileTool(Tool):
    name = "edit_file"
    description = "Replace a specific string in a file with new content. You must read the file first before editing."

    FILE_SIZE_LIMIT = 1 * 1024 * 1024 * 1024  # 1GB

    def __init__(self, read_file_tool: ReadFileTool, cwd: str = "."):
        self._read_tool = read_file_tool
        self.cwd = cwd

    @property
    def _file_mtimes(self) -> dict[str, float]:
        return self._read_tool._file_mtimes

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace (must be unique in file)",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences of old_string (default: false)",
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    def validate(self, input: dict) -> str | None:
        path = input["path"]
        old_string = input["old_string"]
        new_string = input["new_string"]
        replace_all = input.get("replace_all", False)

        if not os.path.exists(path):
            similar = self._find_similar_files(path)
            if similar:
                suggestions = ", ".join(similar[:5])
                return f"File not found: {path}. Similar files: {suggestions}"
            return f"File not found: {path}"

        try:
            size = os.path.getsize(path)
            if size > self.FILE_SIZE_LIMIT:
                return f"File too large: {size} bytes exceeds limit of {self.FILE_SIZE_LIMIT} bytes (1GB)"
        except OSError as e:
            return f"Cannot stat file: {e}"

        safe_err = _is_safe_path(path, self.cwd)
        if safe_err:
            return safe_err

        # Pre-read validation (Claude Code core pattern)
        abs_path = os.path.abspath(path)
        if abs_path not in self._read_tool.read_files:
            return "You must read the file before editing it. Use read_file first."

        # Concurrent modification detection: check if file was externally modified since last read
        if abs_path in self._file_mtimes:
            try:
                current_mtime = os.path.getmtime(path)
                if current_mtime != self._file_mtimes[abs_path]:
                    return "File was modified externally since last read. Please read_file again."
            except OSError:
                pass

        if old_string == new_string:
            return "old_string and new_string are identical. No change needed."

        try:
            with open(path, "r") as f:
                content = f.read()
        except Exception as e:
            return f"Cannot read file: {e}"

        count = content.count(old_string)
        if count == 0:
            return f"old_string not found in {path}. Make sure it matches exactly."
        if count > 1 and not replace_all:
            return f"old_string found {count} times. Provide more surrounding context to make it unique, or set replace_all=true to replace all occurrences."

        return None

    def _find_similar_files(self, path: str) -> list[str]:
        """Find files with similar names in the same directory."""
        directory = os.path.dirname(path) or "."
        basename = os.path.basename(path)
        name_without_ext = os.path.splitext(basename)[0]

        if not os.path.isdir(directory):
            return []

        try:
            candidates = glob.glob(os.path.join(directory, f"*{name_without_ext}*"))
            candidates += glob.glob(os.path.join(directory, f"{name_without_ext[:3]}*"))
            return sorted(set(candidates))
        except Exception:
            return []

    def execute(self, input: dict) -> ToolResult:
        input = dict(input)
        input["path"] = _expand_path(input["path"], self.cwd)
        # G39: auto-redirect accidental main repo path during worktree work
        redirected_path, redirect_notice = _redirect_to_worktree_path(input["path"], self.cwd)
        input["path"] = redirected_path
        error = self.validate(input)
        if error:
            return ToolResult(content=error, is_error=True)

        path = input["path"]
        replace_all = input.get("replace_all", False)
        try:
            with open(path, "r") as f:
                content = f.read()

            old_string = input["old_string"]
            new_string = input["new_string"]

            # Find change location (line number)
            pos = content.find(old_string)
            start_line = content[:pos].count("\n") + 1

            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)

            with open(path, "w") as f:
                f.write(new_content)

            # Update mtime after modification
            abs_path = os.path.abspath(path)
            self._file_mtimes[abs_path] = os.path.getmtime(path)

            # Generate diff (Claude Code style)
            diff = _format_edit_diff(path, old_string, new_string, start_line)
            if redirect_notice:
                diff = redirect_notice + "\n" + diff
            # Secret check
            warnings = _check_secrets(new_string)
            if warnings:
                diff += "\n⚠️ " + "; ".join(warnings)
            return ToolResult(content=diff)
        except Exception as e:
            return ToolResult(content=f"Error editing file: {e}", is_error=True)


__all__ = ["EditFileTool", "_shorten_path", "_format_edit_diff"]
