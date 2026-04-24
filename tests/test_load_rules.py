"""
Characterization tests for _load_rules() at hermit_agent/loop.py:2432-2464.

Purpose: capture current behavior so future refactors cannot regress silently.
Scope-out: _find_rules() at line 79 is a separate function that scans only
.hermit/rules/ (used in _build_dynamic_context and post-compaction re-injection).
The two functions serve different purposes and are not tested here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.loop import _load_rules


def _w(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_load_rules_no_directories_returns_empty(tmp_path):
    """When no rule directories exist, _load_rules returns empty string."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert result == ""


def test_load_rules_empty_directory_returns_empty(tmp_path):
    """Empty rules directory yields empty result."""
    fake_home = tmp_path / "fake_home"
    (fake_home / ".claude" / "rules").mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert result == ""


def test_load_rules_reads_md_file_in_claude_rules(tmp_path):
    """Markdown file in ~/.claude/rules/ is loaded."""
    fake_home = tmp_path / "fake_home"
    claude_rules = fake_home / ".claude" / "rules"
    _w(claude_rules / "test.md", "# Test Rule\n\nThis is a test rule.")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert "Test Rule" in result


def test_load_rules_reads_md_file_in_hermit_rules(tmp_path):
    """Markdown file in ~/.hermit/rules/ is loaded."""
    fake_home = tmp_path / "fake_home"
    _w(fake_home / ".hermit" / "rules" / "hermit_test.md", "# Hermit Rule\n\nHermit-specific rule.")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert "Hermit Rule" in result


def test_load_rules_project_cwd_rules_loaded(tmp_path):
    """Markdown file in {cwd}/.hermit/rules/ is loaded."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    cwd = tmp_path / "project"
    _w(cwd / ".hermit" / "rules" / "proj.md", "# Project Rule\n\nProject-specific.")
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert "Project Rule" in result


def test_load_rules_same_result_when_called_twice(tmp_path):
    """Deterministic — same inputs produce same output.

    Simulates line 2387 (skill execution path) and line 2525 (slash command
    path) both calling _load_rules() with the same cwd — they must return
    identical content.
    """
    fake_home = tmp_path / "fake_home"
    _w(fake_home / ".claude" / "rules" / "a.md", "# A\n")
    _w(fake_home / ".claude" / "rules" / "b.md", "# B\n")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result_1 = _load_rules(cwd=str(cwd))
        result_2 = _load_rules(cwd=str(cwd))
    assert result_1 == result_2, (
        "Same cwd must produce identical rules content "
        "(line 2387 vs line 2525 consistency)"
    )


def test_load_rules_multiple_files_all_included(tmp_path):
    """All .md files in a directory are loaded (not just the first)."""
    fake_home = tmp_path / "fake_home"
    claude_rules = fake_home / ".claude" / "rules"
    _w(claude_rules / "one.md", "RULE_ONE_MARKER")
    _w(claude_rules / "two.md", "RULE_TWO_MARKER")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert "RULE_ONE_MARKER" in result
    assert "RULE_TWO_MARKER" in result


def test_load_rules_ignores_non_md_files(tmp_path):
    """Non-markdown files (e.g., .txt, .json) are not loaded."""
    fake_home = tmp_path / "fake_home"
    claude_rules = fake_home / ".claude" / "rules"
    _w(claude_rules / "rule.md", "MARKDOWN_CONTENT")
    _w(claude_rules / "note.txt", "TEXT_SHOULD_NOT_LOAD")
    _w(claude_rules / "config.json", '{"key": "JSON_SHOULD_NOT_LOAD"}')
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert "MARKDOWN_CONTENT" in result
    assert "TEXT_SHOULD_NOT_LOAD" not in result
    assert "JSON_SHOULD_NOT_LOAD" not in result


def test_load_rules_output_format_has_header(tmp_path):
    """When rules are found, result starts with '--- Rules ---' header."""
    fake_home = tmp_path / "fake_home"
    _w(fake_home / ".claude" / "rules" / "r.md", "CONTENT")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert result.startswith("--- Rules ---")


def test_load_rules_truncates_large_files(tmp_path):
    """Files larger than 3000 chars are truncated with a marker."""
    fake_home = tmp_path / "fake_home"
    large_content = "X" * 4000
    _w(fake_home / ".claude" / "rules" / "big.md", large_content)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=str(cwd))
    assert "[...truncated]" in result
    # Should not contain the full 4000-char content
    assert "X" * 3001 not in result


def test_load_rules_cwd_none_skips_project_dir(tmp_path):
    """When cwd=None, project .hermit/rules/ is not scanned."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    # A project dir with rules — but we won't pass cwd
    project = tmp_path / "project"
    _w(project / ".hermit" / "rules" / "proj.md", "PROJECT_ONLY_MARKER")
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        result = _load_rules(cwd=None)
    assert "PROJECT_ONLY_MARKER" not in result
