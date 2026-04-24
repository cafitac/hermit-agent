"""Skill execution + tool search tools (ToolSearchTool, RunSkillTool).

RunSkillTool supports G29-A lazy-load + G37 decimal phase matching.
"""

from __future__ import annotations

import os
import re

from ..base import Tool, ToolResult


class ToolSearchTool(Tool):
    """Tool search. Find tools by keyword when many are available."""
    name = "tool_search"
    description = "Search available tools by keyword. Use when you need a tool but don't see it."
    is_read_only = True
    is_concurrent_safe = True

    def __init__(self, all_tools: dict):
        self._all_tools = all_tools

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to search tool names and descriptions"},
            },
            "required": ["query"],
        }

    def execute(self, input: dict) -> ToolResult:
        query = input["query"].lower()
        matches = []
        for name, tool in self._all_tools.items():
            if query in name.lower() or query in tool.description.lower():
                matches.append(f"- {name}: {tool.description[:100]}")
        if not matches:
            return ToolResult(content=f"No tools matching '{query}'")
        return ToolResult(content=f"Tools matching '{query}':\n" + "\n".join(matches))


def _normalize_phase_key(value) -> str:
    """Normalize a phase number argument/label into a comparable string.

    - `1`, `1.0`, `"1"`, `"1.00"` → `"1"`
    - `1.5`, `"1.5"`, `"1.50"` → `"1.5"`
    - On parse failure, returns the original string (lowercased and stripped).
    """
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value).strip().lower()
    if f.is_integer():
        return str(int(f))
    # Strip trailing zeros: 1.50 → "1.5"
    return ("%g" % f)


class RunSkillTool(Tool):
    """Execute a skill by name. Implements the Claude Code Skill() call pattern.

    Skills such as feature-develop invoke other skills via
    Skill("oh-my-claudecode:deep-interview").

    Lazy phase loading (G29-A):
      - No phase specified: returns overview (frontmatter to first `## Phase`) + Phase 1 only
      - phase=N: returns only that Phase's content
      - Each phase exceeding PHASE_TOKEN_CAP is truncated with a hint for subsequent calls
    """

    name = "run_skill"
    description = (
        'Execute a named skill. Use this when a skill instructs you to call '
        'Skill("oh-my-claudecode:X") or /skill-name. '
        "By default returns overview + Phase 1 only; use phase=N for later sections."
    )
    is_read_only = True
    is_concurrent_safe = True

    # Phase content token cap (1 token ≈ 3 chars per estimate_tokens)
    PHASE_TOKEN_CAP = 2000
    PHASE_CHAR_CAP = PHASE_TOKEN_CAP * 3

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name, e.g. 'deep-interview' or 'oh-my-claudecode:deep-interview'",
                },
                "args": {
                    "type": "string",
                    "description": "Arguments to pass to the skill (optional)",
                },
                "phase": {
                    "type": ["integer", "number", "string"],
                    "description": (
                        "Phase label number (e.g. 1, 2, or '1.5'). Matches the 'N' in `## Phase N: Title`. "
                        "Omit for default (overview + first Phase). Decimals ('1.5') supported as string."
                    ),
                },
            },
            "required": ["name"],
        }

    def execute(self, input: dict) -> ToolResult:
        from ...skills import SkillRegistry, substitute_arguments, adapt_for_hermit_agent

        raw_name = input.get("name", "").strip()
        args = input.get("args", "")
        phase = input.get("phase")

        skill_name = raw_name.split(":")[-1] if ":" in raw_name else raw_name

        registry = getattr(self, "_test_registry", None) or SkillRegistry()
        skill = registry.get(skill_name)
        if not skill:
            available = ", ".join(s.name for s in registry.list_skills())
            return ToolResult(
                content=f"Skill '{skill_name}' not found. Available: {available}",
                is_error=True,
            )

        full_body = adapt_for_hermit_agent(substitute_arguments(skill.content, args))
        overview, phases = self._split_phases(full_body)

        if not phases:
            # No Phase structure — return full content (legacy behavior)
            resolved_refs = self._resolve_references(full_body)
            trailing = ("\n\n--- Referenced Skills ---\n" + resolved_refs) if resolved_refs else ""
            return ToolResult(
                content=f"[Skill: {skill_name}]\nFollow these instructions:\n\n{full_body}{trailing}"
            )

        available_hint = ", ".join(
            f"phase={p['number']} ({p['title']})" for p in phases
        )

        if phase is None:
            first = phases[0]
            body = self._cap(first["content"], skill_name, first["number"])
            header = (
                f"[Skill: {skill_name} — overview + {first['title']} of {len(phases)}]\n"
                f"Call run_skill(name=\"{skill_name}\", phase=N) to load later sections. "
                f"Available: {available_hint}\n\n"
            )
            return ToolResult(content=header + overview.rstrip() + "\n\n" + body)

        # Normalize the phase argument to a string and match against Phase labels.
        # Accepts "1.5", "1.50", 1.5, 2, etc. Equivalence comparison with "Phase N" labels.
        phase_key = _normalize_phase_key(phase)
        matched = next(
            (p for p in phases if _normalize_phase_key(p["number"]) == phase_key),
            None,
        )
        if matched is None:
            return ToolResult(
                content=(
                    f"[Skill: {skill_name}] Phase {phase} not found. "
                    f"Available: {available_hint}"
                ),
                is_error=True,
            )

        body = self._cap(matched["content"], skill_name, matched["number"])
        header = f"[Skill: {skill_name} — {matched['title']} of {len(phases)}]\n\n"
        return ToolResult(content=header + body)

    @staticmethod
    def _split_phases(text: str) -> tuple[str, list[dict]]:
        """Split body into overview and phases based on `## Phase N` anchors.

        Returns: (overview_text, [{"number": "1", "title": "Phase 1: ...", "content": "..."}])
        The number is the numeric label (integer or decimal, e.g. "0", "1.5").
        If no anchors are found, returns ("", []) and the caller falls back to full return.
        """
        # Match `## Phase N[.M]: Title` headers (case-insensitive; N may be integer or decimal)
        pattern = re.compile(
            r"^##\s+Phase\s+(\d+(?:\.\d+)?)\s*:?\s*(.*)$",
            re.MULTILINE | re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return "", []

        overview = text[:matches[0].start()].rstrip()
        phases: list[dict] = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            number = m.group(1)
            title = f"Phase {number}"
            if m.group(2).strip():
                title += f": {m.group(2).strip()}"
            phases.append({
                "number": number,
                "title": title,
                "content": text[start:end].rstrip(),
            })
        return overview, phases

    @classmethod
    def _cap(cls, content: str, skill_name: str, phase_num) -> str:
        if len(content) <= cls.PHASE_CHAR_CAP:
            return content
        truncated = content[: cls.PHASE_CHAR_CAP]
        notice = (
            f"\n\n[...truncated — call run_skill(name=\"{skill_name}\", "
            f"phase={phase_num}, section=\"<keyword>\") for the rest]"
        )
        return truncated + notice

    def _resolve_references(self, content: str) -> str:
        """Automatically load .md files referenced in skill content."""
        ref_pattern = re.compile(r'`(~/.(?:claude|hermit_agent)/commands/[^`]+\.md)`')
        refs = ref_pattern.findall(content)
        if not refs:
            return ""

        sections = []
        seen: set[str] = set()
        for ref_path in refs:
            expanded = os.path.expanduser(ref_path)
            if expanded in seen or not os.path.isfile(expanded):
                continue
            seen.add(expanded)
            try:
                with open(expanded) as f:
                    ref_content = f.read()
                if len(ref_content) > 5000:
                    ref_content = ref_content[:5000] + "\n[...truncated]"
                sections.append(f"## {os.path.basename(expanded)}\n{ref_content}")
            except Exception:
                continue
        return "\n\n".join(sections)


__all__ = ['ToolSearchTool', 'RunSkillTool', '_normalize_phase_key']
