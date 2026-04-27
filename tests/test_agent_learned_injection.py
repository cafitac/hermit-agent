"""Step 3 TDD: agent-learned.md READ path — loaded into context."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

from hermit_agent.loop_context import _find_rules, ProjectConfigLoader


def test_agent_learned_md_loaded_by_find_rules(tmp_path):
    """_find_rules must include content from .hermit/rules/agent-learned.md."""
    rules_dir = tmp_path / ".hermit" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "agent-learned.md").write_text(
        "# Learned Rules\n\n## test-rule\nalways test first\n",
        encoding="utf-8",
    )

    result = _find_rules(str(tmp_path), depth="shallow")
    assert "always test first" in result


def test_agent_learned_md_missing_no_error(tmp_path):
    """_find_rules returns empty string when agent-learned.md does not exist."""
    result = _find_rules(str(tmp_path), depth="shallow")
    assert result == ""


def test_agent_learned_md_alongside_other_rules(tmp_path):
    """agent-learned.md loads alongside other rule files."""
    rules_dir = tmp_path / ".hermit" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "coding-style.md").write_text("Use 4-space indent\n", encoding="utf-8")
    (rules_dir / "agent-learned.md").write_text(
        "## learned\nprefer edit_file over write_file\n",
        encoding="utf-8",
    )

    result = _find_rules(str(tmp_path), depth="shallow")
    assert "4-space indent" in result
    assert "edit_file over write_file" in result
