"""Phase 1 TDD: `learner.py` auto-learned feature test."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermit_agent.learner import (
    AUTO_LEARNED_DIR,
    Learner,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Use an independent temporary directory for each test."""
    auto_dir = tmp_path / "auto-learned"
    approved_dir = tmp_path / "approved"
    pending_dir = tmp_path / "pending"
    deprecated_dir = tmp_path / "deprecated"

    monkeypatch.setattr("hermit_agent.learner.AUTO_LEARNED_DIR", str(auto_dir))
    monkeypatch.setattr("hermit_agent.learner.APPROVED_DIR", str(approved_dir))
    monkeypatch.setattr("hermit_agent.learner.PENDING_DIR", str(pending_dir))
    monkeypatch.setattr("hermit_agent.learner.DEPRECATED_DIR", str(deprecated_dir))

    yield {
        "auto": auto_dir,
        "approved": approved_dir,
        "pending": pending_dir,
        "deprecated": deprecated_dir,
    }


@pytest.fixture
def learner():
    mock_llm = MagicMock()
    return Learner(llm=mock_llm)


@pytest.fixture
def skill_data():
    return {
        "name": "test_auto_skill",
        "description": "Test auto-learned skill",
        "triggers": ["pytest", "test"],
        "scope": ["tests/"],
        "rule": "Check for uncommitted changes before running pytest",
        "why": "Uncommitted changes may cause test pollution",
        "good_pattern": "git stash && pytest",
        "bad_pattern": "pytest (running directly with uncommitted changes)",
    }


# ---------------------------------------------------------------------------
# AUTO_LEARNED_DIR constant
# ---------------------------------------------------------------------------

def test_auto_learned_dir_constant_exists():
    """The `AUTO_LEARNED_DIR` constant must exist."""
    assert AUTO_LEARNED_DIR is not None
    assert "auto-learned" in AUTO_LEARNED_DIR


# ---------------------------------------------------------------------------
# save_auto_learned
# ---------------------------------------------------------------------------

def test_save_auto_learned_creates_file(learner, skill_data, isolated_dirs):
    """`save_auto_learned()` must create a file in `auto-learned/`."""
    path = learner.save_auto_learned(skill_data)

    assert path is not None
    assert Path(path).exists()
    assert "auto-learned" in path


def test_save_auto_learned_separate_from_approved(learner, skill_data, isolated_dirs):
    """auto-learned skills must not be saved in the `approved/` folder."""
    path = learner.save_auto_learned(skill_data)

    approved_dir = isolated_dirs["approved"]
    assert not (approved_dir / f"{skill_data['name']}.md").exists()
    assert "auto-learned" in path


def test_save_auto_learned_has_type_frontmatter(learner, skill_data, isolated_dirs):
    """The saved file's frontmatter must contain `type: auto-learned`."""
    path = learner.save_auto_learned(skill_data)

    content = Path(path).read_text()
    assert "type: auto-learned" in content


def test_save_auto_learned_overwrites_existing(learner, skill_data, isolated_dirs):
    """If a skill with the same name already exists, it must be overwritten (no pending)."""
    path1 = learner.save_auto_learned(skill_data)

    updated = {**skill_data, "description": "Updated description"}
    path2 = learner.save_auto_learned(updated)

    assert path1 == path2
    content = Path(path2).read_text()
    assert "Updated description" in content


def test_save_auto_learned_returns_none_on_missing_name(learner, isolated_dirs):
    """Must return `None` if `name` is missing."""
    result = learner.save_auto_learned({"description": "Skill without a name"})
    assert result is None


# ---------------------------------------------------------------------------
# extract_from_success
# ---------------------------------------------------------------------------

def test_extract_from_success_returns_none_below_threshold(learner):
    """Must return `None` if `tool_call_count < 5`."""
    messages = [{"role": "user", "content": "Task request"}]
    result = learner.extract_from_success(messages, tool_call_count=3)
    assert result is None
    learner.llm.chat.assert_not_called()


def test_extract_from_success_calls_llm_above_threshold(learner):
    """Must call LLM if `tool_call_count >= 5`."""
    learner.llm.chat.return_value = MagicMock(
        content='{"name": "new_skill", "description": "desc", "triggers": ["x"], "rule": "r", "why": "w", "good_pattern": "g", "bad_pattern": "b"}'
    )
    messages = [{"role": "user", "content": "Complex task"}]
    result = learner.extract_from_success(messages, tool_call_count=5)

    learner.llm.chat.assert_called_once()
    assert result is not None
    assert result["name"] == "new_skill"


def test_extract_from_success_returns_none_on_llm_none(learner):
    """Must return `None` if LLM returns `NONE`."""
    learner.llm.chat.return_value = MagicMock(content="NONE")
    messages = [{"role": "user", "content": "Task"}]
    result = learner.extract_from_success(messages, tool_call_count=10)
    assert result is None


def test_extract_from_success_returns_none_on_llm_error(learner):
    """Must return `None` even if an exception occurs during LLM invocation (do not abort session)."""
    learner.llm.chat.side_effect = Exception("LLM connection error")
    messages = [{"role": "user", "content": "Task"}]
    result = learner.extract_from_success(messages, tool_call_count=10)
    assert result is None


# ---------------------------------------------------------------------------
# get_active_skills — including auto-learned
# ---------------------------------------------------------------------------

def test_get_active_skills_includes_auto_learned(learner, skill_data, isolated_dirs):
    """`get_active_skills()` must also return auto-learned skills."""
    learner.save_auto_learned(skill_data)

    skills = learner.get_active_skills(context_keywords=["pytest"])
    names = [name for name, _ in skills]

    assert "test_auto_skill" in names


def test_get_active_skills_auto_learned_no_keyword_returns_all(learner, skill_data, isolated_dirs):
    """Must return all auto-learned skills if no keyword is provided."""
    learner.save_auto_learned(skill_data)

    skills = learner.get_active_skills(context_keywords=None)
    names = [name for name, _ in skills]

    assert "test_auto_skill" in names


# ---------------------------------------------------------------------------
# status_report — including auto-learned count
# ---------------------------------------------------------------------------

def test_status_report_includes_auto_learned_count(learner, skill_data, isolated_dirs):
    """`status_report()` must display the auto-learned count."""
    learner.save_auto_learned(skill_data)

    report = learner.status_report()
    assert "auto-learned" in report
    assert "1" in report
