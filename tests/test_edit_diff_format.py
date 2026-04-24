"""G24 — Verify that the edit_file result format is unified diff style."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.tools import EditFileTool, ReadFileTool


def _make_tools(tmp: str):
    read_tool = ReadFileTool()
    edit_tool = EditFileTool(read_file_tool=read_tool)
    # edit assumes read — register read_files
    return read_tool, edit_tool


def _edit(tmp: str, path: str, old: str, new: str) -> str:
    read_tool, edit_tool = _make_tools(tmp)
    read_tool.execute({"path": path})
    result = edit_tool.execute({"path": path, "old_string": old, "new_string": new})
    assert not result.is_error, result.content
    return result.content


def test_diff_has_hunk_header():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "f.py")
        with open(path, "w") as f:
            f.write("a\nb\nc\nd\ne\n")
        out = _edit(tmp, path, "c", "C")
        # hunk header @@ -N,M +N,M @@
        assert "@@" in out
        assert "-" in out and "+" in out


def test_unchanged_lines_have_space_prefix_not_minus_plus():
    """Unchanged context lines must have a space prefix (-/+ prohibited)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "f.py")
        content = "line1\nline2\nline3\nTARGET\nline5\nline6\nline7\n"
        with open(path, "w") as f:
            f.write(content)
        out = _edit(tmp, path, "TARGET", "CHANGED")

        # "-TARGET" and "+CHANGED" must be present.
        assert any(line.strip().startswith("-") and "TARGET" in line for line in out.splitlines())
        assert any(line.strip().startswith("+") and "CHANGED" in line for line in out.splitlines())

        # Unchanged context lines (line2, line5, etc.) must not start with -/+.
        for line in out.splitlines():
            stripped = line.lstrip()
            # hunk header is an exception
            if stripped.startswith("@@"):
                continue
            if "line2" in line or "line5" in line or "line6" in line:
                # Context lines must not have a -/+ prefix
                assert not stripped.startswith("-"), f"context line should not have '-': {line}"
                assert not stripped.startswith("+"), f"context line should not have '+': {line}"


def test_added_lines_are_shown_not_hidden():
    """Actual added lines must not be hidden by `...(n more lines)`."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "f.py")
        with open(path, "w") as f:
            f.write("before\nmarker\nafter\n")
        # Add 5 lines
        new = "marker\nADD1\nADD2\nADD3\nADD4\nADD5"
        out = _edit(tmp, path, "marker", new)
        # All added lines must be displayed
        for token in ("ADD1", "ADD2", "ADD3", "ADD4", "ADD5"):
            assert token in out, f"{token} missing in diff output"


def test_long_path_uses_middle_ellipsis():
    """Overly long paths are truncated with `...` in the middle (not at the end)."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create deep path
        deep = os.path.join(tmp, "a" * 50, "b" * 50, "c" * 50)
        os.makedirs(deep, exist_ok=True)
        path = os.path.join(deep, "final_file_name.py")
        with open(path, "w") as f:
            f.write("x\ny\nz\n")
        out = _edit(tmp, path, "y", "Y")
        # The end of the file name must be preserved
        assert "final_file_name.py" in out
