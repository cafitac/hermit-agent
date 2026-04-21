"""
Skill trigger reliability test.

Ensures migrated CC skills are loadable and contain expected trigger keywords
in their YAML description. Prevents silent trigger-failure regressions.
"""
import os
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:
    yaml = None


CLAUDE_SKILLS_DIR = Path(os.path.expanduser("~/.claude/skills"))


def _parse_skill(path: Path) -> dict:
    """Parse SKILL.md frontmatter and body."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return {"frontmatter": {}, "body": content}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {"frontmatter": {}, "body": content}
    frontmatter_text = parts[1].strip()
    body = parts[2].strip()
    if yaml is not None:
        fm = yaml.safe_load(frontmatter_text) or {}
    else:
        # Fallback: manual name/description extraction
        fm = {}
        for line in frontmatter_text.splitlines():
            if line.startswith("name:"):
                fm["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                fm["description"] = line.split(":", 1)[1].strip()
    return {"frontmatter": fm, "body": body}


# Curated trigger keyword expectations per migrated skill
EXPECTED_TRIGGERS = {
    "hermit-mcp": ["run_task", "reply_task", "check_task", "task_id", "MCP"],
    "feedback-learning": ["feedback", "correction", "learning", "피드백", "학습"],
}


@pytest.mark.parametrize("skill_name", list(EXPECTED_TRIGGERS.keys()))
def test_migrated_skill_exists(skill_name):
    """Migrated skill directory + SKILL.md must exist in ~/.claude/skills/."""
    if not CLAUDE_SKILLS_DIR.exists():
        pytest.skip(f"Claude skills directory not present: {CLAUDE_SKILLS_DIR}")
    skill_path = CLAUDE_SKILLS_DIR / skill_name / "SKILL.md"
    assert skill_path.exists(), f"Missing skill: {skill_path}"


@pytest.mark.parametrize("skill_name,keywords", list(EXPECTED_TRIGGERS.items()))
def test_migrated_skill_has_trigger_keywords(skill_name, keywords):
    """Each migrated skill's frontmatter description must include domain keywords."""
    skill_path = CLAUDE_SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        pytest.skip(f"Skill {skill_name} not yet migrated")
    parsed = _parse_skill(skill_path)
    description = str(parsed["frontmatter"].get("description", ""))
    missing = [k for k in keywords if k not in description]
    assert not missing, (
        f"{skill_name} description missing trigger keywords: {missing}\n"
        f"description: {description[:200]}"
    )


@pytest.mark.parametrize("skill_name", list(EXPECTED_TRIGGERS.keys()))
def test_migrated_skill_frontmatter_valid(skill_name):
    """Frontmatter must contain 'name' and non-empty 'description'."""
    skill_path = CLAUDE_SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        pytest.skip(f"Skill {skill_name} not yet migrated")
    parsed = _parse_skill(skill_path)
    fm = parsed["frontmatter"]
    assert fm.get("name") == skill_name, f"frontmatter name mismatch for {skill_name}"
    description = fm.get("description", "")
    assert description and len(str(description).strip()) > 20, (
        f"{skill_name} description too short or empty"
    )


def test_old_rules_files_removed():
    """Migrated rules files must be deleted (no duplicate source)."""
    old_hermit_mcp = Path(os.path.expanduser("~/.claude/rules/hermit-mcp.md"))
    old_feedback = Path(os.path.expanduser("~/.claude/rules/feedback-learning.md"))
    assert not old_hermit_mcp.exists(), f"Stale file still exists: {old_hermit_mcp}"
    assert not old_feedback.exists(), f"Stale file still exists: {old_feedback}"
