"""G39 — Automatically redirect main repo absolute paths to worktree paths when working inside a worktree.

When HermitAgent is operating in a worktree cwd (`.worktrees/<branch>/`) and the LLM specifies
the same relative path in the main repo as an absolute path, it auto-redirects to the identical file inside the worktree.
Redirect only in this case; other edits outside the cwd are allowed as-is for CC compatibility.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.tools import EditFileTool, ReadFileTool, WriteFileTool


def _make_edit_tool(cwd: str, pre_read: list[str] | None = None) -> EditFileTool:
    read_tool = ReadFileTool()
    for p in pre_read or []:
        read_tool.read_files.add(os.path.abspath(p))
    return EditFileTool(read_file_tool=read_tool, cwd=cwd)


def _make_worktree_fixture(tmp: str) -> tuple[str, str]:
    """Create a temporary git repo + worktree. Returns (main_root, worktree_root)."""
    main = os.path.join(tmp, "repo")
    os.makedirs(main)
    subprocess.run(["git", "init", "-q"], cwd=main, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                   "--allow-empty", "-m", "init", "-q"], cwd=main, check=True)

    target_path = os.path.join(main, "src", "service.py")
    os.makedirs(os.path.dirname(target_path))
    with open(target_path, "w") as f:
        f.write("original = 1\n")
    subprocess.run(["git", "add", "."], cwd=main, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                   "-m", "add service", "-q"], cwd=main, check=True)
    subprocess.run(["git", "branch", "feat"], cwd=main, check=True)

    wt = os.path.join(main, ".worktrees", "feat")
    subprocess.run(["git", "worktree", "add", wt, "feat", "-q"], cwd=main, check=True)
    return main, wt


def test_edit_absolute_main_path_redirects_to_worktree_when_exists():
    """Call edit with main repo absolute path → redirect to the identical file in the worktree."""
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = _make_worktree_fixture(tmp)
        main_file = os.path.join(main, "src", "service.py")
        wt_file = os.path.join(wt, "src", "service.py")

        # Pre-read worktree file (satisfies read-before-edit requirement)
        tool = _make_edit_tool(cwd=wt, pre_read=[wt_file])
        result = tool.execute({
            "path": main_file,  # Intended target is worktree but specified as main repo
            "old_string": "original = 1",
            "new_string": "original = 2",
        })

        assert not result.is_error, result.content
        # worktree file is modified
        assert open(wt_file).read() == "original = 2\n"
        # main repo file remains unchanged
        assert open(main_file).read() == "original = 1\n"
        # Include redirect notice in tool_result
        assert "redirect" in result.content.lower() or "worktree" in result.content.lower()


def test_edit_absolute_main_path_without_worktree_version_keeps_original_path():
    """Do not redirect files that only exist in the main repo and not in the worktree (CC compatibility)."""
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = _make_worktree_fixture(tmp)
        only_in_main = os.path.join(main, "main_only.py")
        with open(only_in_main, "w") as f:
            f.write("main_only = True\n")

        tool = _make_edit_tool(cwd=wt, pre_read=[only_in_main])
        result = tool.execute({
            "path": only_in_main,
            "old_string": "main_only = True",
            "new_string": "main_only = False",
        })

        assert not result.is_error, result.content
        # Main file is actually modified (no redirect since it doesn't exist in worktree)
        assert open(only_in_main).read() == "main_only = False\n"
        # Identical file is not created in the worktree
        assert not os.path.exists(os.path.join(wt, "main_only.py"))


def test_edit_path_inside_worktree_no_redirect():
    """Paths already inside the worktree are edited as-is without redirecting."""
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = _make_worktree_fixture(tmp)
        wt_file = os.path.join(wt, "src", "service.py")

        tool = _make_edit_tool(cwd=wt, pre_read=[wt_file])
        result = tool.execute({
            "path": wt_file,
            "old_string": "original = 1",
            "new_string": "original = 99",
        })

        assert not result.is_error, result.content
        assert open(wt_file).read() == "original = 99\n"
        assert "redirect" not in result.content.lower()


def test_write_file_absolute_main_path_redirects_to_worktree():
    """Apply the same redirect logic to write_file (but only if the target path exists in the worktree)."""
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = _make_worktree_fixture(tmp)
        main_file = os.path.join(main, "src", "service.py")
        wt_file = os.path.join(wt, "src", "service.py")

        tool = WriteFileTool(cwd=wt)
        result = tool.execute({
            "path": main_file,
            "content": "replaced = 1\n",
        })

        assert not result.is_error, result.content
        assert open(wt_file).read() == "replaced = 1\n"
        # main repo file remains unchanged
        assert open(main_file).read() == "original = 1\n"


def test_cwd_not_worktree_no_redirect():
    """Do not redirect if cwd is not a worktree (maintain normal repo behavior)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        target = os.path.join(tmp, "other_project", "file.py")
        os.makedirs(os.path.dirname(target))
        with open(target, "w") as f:
            f.write("x = 1\n")

        tool = _make_edit_tool(cwd=repo, pre_read=[target])
        result = tool.execute({
            "path": target,
            "old_string": "x = 1",
            "new_string": "x = 2",
        })

        assert not result.is_error, result.content
        assert open(target).read() == "x = 2\n"
