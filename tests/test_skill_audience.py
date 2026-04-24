"""Skill `audience` metadata — Separating HermitAgent/Claude Code sharing.

Specifies which agent should load this skill via the optional `audience:` field in SKILL.md frontmatter.

Policy (hermit_agent perspective):
- No field → load (backwards compat)
- `audience: hermit_agent` → load
- `audience: both` → load
- `audience: claude-code` → **do not load** (not for HermitAgent)
- `audience: hermit_agent, claude-code` → load (list includes hermit_agent)

Red-Green:
1. Skill.audience field / audience parsing in _parse_skill / no SkillRegistry filter → Red
2. Implementation → Green
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.skills import SkillRegistry, _parse_skill


SKILL_TEMPLATE = """---
name: {name}
description: test skill
{extra}---

body here
"""


def _make_skill(tmp: str, name: str, audience: str | None) -> Path:
    """Create tmp/name/SKILL.md (optional audience frontmatter)."""
    extra = f"audience: {audience}\n" if audience else ""
    skill_dir = Path(tmp) / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SKILL_TEMPLATE.format(name=name, extra=extra))
    return skill_dir


def test_parse_skill_audience_field_optional():
    """None if no audience."""
    parsed = _parse_skill("---\nname: x\ndescription: d\n---\nbody")
    assert parsed is not None
    assert parsed.audience is None


def test_parse_skill_audience_single():
    parsed = _parse_skill("---\nname: x\ndescription: d\naudience: hermit_agent\n---\nbody")
    assert parsed is not None
    assert parsed.audience == ["hermit_agent"]


def test_parse_skill_audience_list():
    parsed = _parse_skill("---\nname: x\ndescription: d\naudience: hermit_agent, claude-code\n---\nbody")
    assert parsed is not None
    assert set(parsed.audience) == {"hermit_agent", "claude-code"}


def _registry_with_skills_dir(tmp: str) -> SkillRegistry:
    """Workaround to make SkillRegistry load only a single tmp directory."""
    reg = SkillRegistry.__new__(SkillRegistry)
    reg.skills = {}
    reg._load_from_dir(tmp, "user")
    return reg


def test_registry_loads_skill_without_audience():
    with tempfile.TemporaryDirectory() as tmp:
        _make_skill(tmp, "alpha", audience=None)
        reg = _registry_with_skills_dir(tmp)
        assert reg.get("alpha") is not None


def test_registry_loads_skill_with_audience_hermit_agent():
    with tempfile.TemporaryDirectory() as tmp:
        _make_skill(tmp, "beta", audience="hermit_agent")
        reg = _registry_with_skills_dir(tmp)
        assert reg.get("beta") is not None


def test_registry_loads_skill_with_audience_both():
    with tempfile.TemporaryDirectory() as tmp:
        _make_skill(tmp, "gamma", audience="both")
        reg = _registry_with_skills_dir(tmp)
        assert reg.get("gamma") is not None


def test_registry_skips_claude_code_only_skill():
    with tempfile.TemporaryDirectory() as tmp:
        _make_skill(tmp, "delta", audience="claude-code")
        reg = _registry_with_skills_dir(tmp)
        assert reg.get("delta") is None


def test_registry_loads_list_including_hermit_agent():
    with tempfile.TemporaryDirectory() as tmp:
        _make_skill(tmp, "eps", audience="hermit_agent, claude-code")
        reg = _registry_with_skills_dir(tmp)
        assert reg.get("eps") is not None


def test_registry_skips_list_excluding_hermit_agent():
    with tempfile.TemporaryDirectory() as tmp:
        _make_skill(tmp, "zeta", audience="claude-code, hermes")
        reg = _registry_with_skills_dir(tmp)
        assert reg.get("zeta") is None
