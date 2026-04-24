"""G29-A: Skill lazy-load (per phase) test.

`run_skill(name)` call returns only overview + Phase 1 (< 2K tokens).
`run_skill(name, phase=N)` call returns only that Phase.
Requesting a non-existent phase returns the list of available phases.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.skills import SkillRegistry
from hermit_agent.tools import RunSkillTool


SAMPLE_SKILL = """---
name: sample-phased
description: Sample multi-phase skill
---

<Purpose>
Sample overview before any phase.
</Purpose>

<Execution_Policy>
- Always do X
- Never do Y
</Execution_Policy>

## Phase 1: Initialize

Step 1a: do this.
Step 1b: do that.

## Phase 2: Execute

Step 2a: execute the plan.
Step 2b: verify outcome.

## Phase 3: Cleanup

Step 3a: clean up state.

<Advanced>
Some trailing advanced notes.
</Advanced>
"""


def _install_sample(tmpdir: str) -> None:
    d = os.path.join(tmpdir, "sample-phased")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write(SAMPLE_SKILL)


def _make_tool_with_registry(tmpdir: str) -> RunSkillTool:
    _install_sample(tmpdir)
    reg = SkillRegistry.__new__(SkillRegistry)
    reg.skills = {}
    reg._load_from_dir(tmpdir, "project")
    tool = RunSkillTool()
    tool._test_registry = reg  # type: ignore[attr-defined]
    return tool


def _estimate_tokens(text: str) -> int:
    return len(text) // 3


def test_default_returns_overview_and_phase_1_only():
    """If phase is unspecified, return up to Phase 1 only. No Phase 2/3 body."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_tool_with_registry(tmp)
        result = tool.execute({"name": "sample-phased"})
        assert not result.is_error
        content = result.content
        # overview (Purpose, Execution_Policy) included
        assert "Sample overview before any phase" in content
        assert "Always do X" in content
        # Phase 1 included
        assert "Phase 1: Initialize" in content
        assert "Step 1a: do this" in content
        # Phase 2 / 3 body must NOT be inlined
        assert "Step 2a: execute the plan" not in content
        assert "Step 3a: clean up state" not in content


def test_phase_1_total_size_under_2k_tokens():
    """Returning only Phase 1 results in a total size under 2000 tokens."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_tool_with_registry(tmp)
        result = tool.execute({"name": "sample-phased"})
        assert _estimate_tokens(result.content) < 2000


def test_explicit_phase_returns_that_phase():
    """Specifying phase=2 returns the Phase 2 body."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_tool_with_registry(tmp)
        result = tool.execute({"name": "sample-phased", "phase": 2})
        assert not result.is_error
        assert "Phase 2: Execute" in result.content
        assert "Step 2a: execute the plan" in result.content
        # Phase 1 body contains no duplicates
        assert "Step 1a: do this" not in result.content


def test_invalid_phase_returns_available_list():
    """Requesting a non-existent phase returns the list of available phases."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_tool_with_registry(tmp)
        result = tool.execute({"name": "sample-phased", "phase": 99})
        # Can be indicated as an error or as a normal result — verify based on content
        assert "Phase" in result.content
        assert "1" in result.content and "2" in result.content and "3" in result.content
        # Explicitly indicate that it is a list of available phases
        assert "available" in result.content.lower()


def test_truncation_notice_when_phase_exceeds_cap():
    """If a Phase body exceeds the 2000 token cap, include a truncated notice."""
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "big-skill")
        os.makedirs(d)
        huge_body = "lorem ipsum " * 3000  # ~36000 chars ≈ 12000 tokens
        content = f"""---
name: big-skill
description: Big phased skill
---

## Phase 1: Huge
{huge_body}

## Phase 2: Small
Just a line.
"""
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write(content)

        reg = SkillRegistry.__new__(SkillRegistry)
        reg.skills = {}
        reg._load_from_dir(tmp, "project")
        tool = RunSkillTool()
        tool._test_registry = reg  # type: ignore[attr-defined]

        result = tool.execute({"name": "big-skill"})
        assert "truncated" in result.content.lower()
        assert "run_skill" in result.content


# ─── G37: Support for non-integer phase numbers (e.g., Phase 1.5) ───────────────


DECIMAL_SKILL = """---
name: decimal-phased
description: Skill with decimal phase number (Phase 0, 1, 1.5, 2)
---

Intro overview.

## Phase 0: Collect

Gather PR info.

## Phase 1: Interview

Interview the user.

## Phase 1.5: Pattern Exploration

Brownfield探索.

## Phase 2: Plan

Write the plan.
"""


def _make_decimal_tool(tmp: str) -> RunSkillTool:
    d = os.path.join(tmp, "decimal-phased")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write(DECIMAL_SKILL)
    reg = SkillRegistry.__new__(SkillRegistry)
    reg.skills = {}
    reg._load_from_dir(tmp, "project")
    tool = RunSkillTool()
    tool._test_registry = reg  # type: ignore[attr-defined]
    return tool


def test_decimal_phase_matches_by_label():
    """Requesting phase='1.5' returns the 'Phase 1.5: Pattern Exploration' body."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_decimal_tool(tmp)
        result = tool.execute({"name": "decimal-phased", "phase": "1.5"})
        assert not result.is_error, result.content
        assert "Phase 1.5" in result.content
        assert "Pattern Exploration" in result.content
        # Other phase bodies are not mixed in
        assert "Collect" not in result.content
        assert "Write the plan" not in result.content


def test_phase_by_label_zero_phase_supported():
    """Requesting phase=0 returns the 'Phase 0: Collect' body."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_decimal_tool(tmp)
        result = tool.execute({"name": "decimal-phased", "phase": 0})
        assert not result.is_error, result.content
        assert "Phase 0" in result.content
        assert "Collect" in result.content


def test_phase_arg_matches_label_number_not_sequential_index():
    """phase=2 should return 'Phase 2: Plan', not the third block (Phase 1.5)."""
    with tempfile.TemporaryDirectory() as tmp:
        tool = _make_decimal_tool(tmp)
        result = tool.execute({"name": "decimal-phased", "phase": 2})
        assert not result.is_error, result.content
        assert "Phase 2" in result.content
        assert "Write the plan" in result.content
        assert "Pattern Exploration" not in result.content
