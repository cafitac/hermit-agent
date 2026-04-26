"""Slash command dispatch and preprocessing utilities."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..loop import AgentLoop

from ..loop_context import _write_task_state, _find_project_config
from ._registry import SLASH_COMMANDS, TRIGGER_AGENT


def handle_slash_command(agent: "AgentLoop", input_text: str) -> str | None:
    """Handle slash commands.

    Return values:
    - str: output directly
    - TRIGGER_AGENT: trigger agent execution (message already added)
    - None: not a slash command
    """
    if not input_text.startswith("/"):
        return None

    parts = input_text[1:].split(None, 1)
    cmd_name = parts[0].lower()
    cmd_args = parts[1] if len(parts) > 1 else ""

    # Built-in commands
    if cmd_name in SLASH_COMMANDS:
        return SLASH_COMMANDS[cmd_name]["func"](agent, cmd_args)

    # Execute directly by skill/command name
    from ..skills import SkillRegistry

    registry = SkillRegistry()
    skill = registry.get(cmd_name)
    if skill:
        # Claude Code's substituteArguments() pattern: $ARGUMENTS, $0, $ARGUMENTS[n] substitution
        from ..skills import adapt_for_hermit_agent, substitute_arguments

        skill_content = adapt_for_hermit_agent(substitute_arguments(skill.content, cmd_args))
        args_section = f"\nArguments: {cmd_args}" if cmd_args.strip() else ""
        # Auto-load .md files referenced within the skill (Claude Code pattern)
        resolved_refs = _resolve_skill_references(skill_content)
        if resolved_refs:
            skill_content += "\n\n--- Referenced Skills ---\n" + resolved_refs
        # If the skill has interview/interactive steps, instruct to wait for user input
        interactive_hint = ""
        if any(kw in skill_content.lower() for kw in ["interview", "ask the user"]):
            interactive_hint = "IMPORTANT: When the skill requires an interview or user input, you MUST stop and ask the user questions. Wait for their response before proceeding to the next phase.\n"

        # Load rules (global + project `.hermit/rules/`)
        rules_section = _load_rules(cwd=agent.cwd)

        # SDD task state initialization -- create task_state.md at skill start
        _write_task_state(agent.cwd, cmd_name, cmd_args, skill_content)
        agent._skill_active = True  # Enable auto-continue

        # KB domain knowledge injection (matching skill-related keywords)
        kb_section = ""
        try:
            from ..kb_learner import KBLearner

            kb = KBLearner(cwd=agent.cwd)
            context_keywords = [w for w in (cmd_args + " " + cmd_name).split() if len(w) > 2]
            kb_content = kb.format_for_injection(context_keywords or None)
            if kb_content:
                kb_section = f"--- Domain Knowledge (KB) ---\n{kb_content}\n\n"
        except Exception:
            pass

        agent.messages.append(
            {
                "role": "user",
                "content": (
                    f"Execute this skill NOW. Do NOT explain — start executing immediately using tools (bash, read_file, edit_file, etc.).\n"
                    f"Follow the steps exactly as written. Do NOT run ls or explore first.\n"
                    f"{interactive_hint}"
                    f"Working directory: {agent.cwd}{args_section}\n\n"
                    f"IMPORTANT: A task state file has been created at `{agent.cwd}/.hermit/task_state.md`. "
                    f"Update this file as you complete each step (use edit_file). "
                    f"If context is compressed, re-read this file to restore your progress.\n\n"
                    f"{rules_section}"
                    f"--- Project Config ---\n{_find_project_config(agent.cwd)}\n\n"
                    f"{kb_section}"
                    f"--- Skill ---\n{skill_content}"
                ),
            }
        )
        return TRIGGER_AGENT

    return f"Unknown command: /{cmd_name}. Type /help for available commands."


def _load_rules(cwd: str | None = None) -> str:
    """Load rule files. Claude Code pattern + project-local `.hermit/rules/`.

    Search order:
    1. `~/.hermit/rules/*.md` (HermitAgent global)
    2. `~/.claude/rules/*.md` (Claude Code global)
    3. `{cwd}/.hermit/rules/*.md` (project-specific -- only if cwd is given)

    Called from two sites with identical behavior:
    - skill execution path (agent.cwd)
    - slash command preprocessing (cwd)

    Related: _find_rules() is a separate function that scans only
    .hermit/rules/ (used in _build_dynamic_context and post-compaction
    re-injection). The two functions serve different purposes and should
    not be merged.

    Behavior is characterized by tests/test_load_rules.py — any refactor
    must preserve the test suite outcomes.
    """
    from pathlib import Path

    dirs = [
        os.path.expanduser("~/.hermit/rules"),
        os.path.expanduser("~/.claude/rules"),
    ]
    if cwd:
        dirs.append(os.path.join(cwd, ".hermit", "rules"))

    sections = []
    for rules_dir in dirs:
        if not os.path.isdir(rules_dir):
            continue
        for f in sorted(Path(rules_dir).glob("*.md")):
            try:
                content = f.read_text()
                # Size limit (context protection)
                if len(content) > 3000:
                    content = content[:3000] + "\n[...truncated]"
                sections.append(f"# Rules: {f.name}\n{content}")
            except Exception:
                continue
    if sections:
        return "--- Rules ---\n" + "\n\n".join(sections) + "\n\n"
    return ""


def _resolve_skill_references(content: str) -> str:
    """Auto-load .md files referenced in skill content.

    Pattern: `~/.claude/commands/xxx.md` or `~/.hermit/commands/xxx.md`
    """
    import re

    ref_pattern = re.compile(r"`(~/.(?:claude|hermit_agent)/commands/[^`]+\.md)`")
    refs = ref_pattern.findall(content)
    if not refs:
        return ""

    sections = []
    seen = set()
    for ref_path in refs:
        expanded = os.path.expanduser(ref_path)
        if expanded in seen or not os.path.isfile(expanded):
            continue
        seen.add(expanded)
        try:
            with open(expanded) as f:
                ref_content = f.read()
            # Reference size limit (context protection)
            if len(ref_content) > 5000:
                ref_content = ref_content[:5000] + "\n[...truncated]"
            sections.append(f"## {os.path.basename(expanded)}\n{ref_content}")
        except Exception:
            continue
    return "\n\n".join(sections)


def _preprocess_slash_command(full_task: str, slash_line: str, cwd: str) -> str:
    """Convert /skill-name args slash commands to skill content in MCP/Gateway mode.

    Produces the same result as handle_slash_command() in CLI mode.
    full_task may include a learned_feedback block, which is preserved as a prefix.
    """
    from ..skills import SkillRegistry, adapt_for_hermit_agent, substitute_arguments

    parts = slash_line[1:].split(None, 1)
    cmd_name = parts[0].lower()
    cmd_args = parts[1] if len(parts) > 1 else ""

    registry = SkillRegistry()
    skill = registry.get(cmd_name)
    if not skill:
        return full_task  # No skill found, pass through as-is

    skill_content = adapt_for_hermit_agent(substitute_arguments(skill.content, cmd_args))
    args_section = f"\nArguments: {cmd_args}" if cmd_args.strip() else ""
    resolved_refs = _resolve_skill_references(skill_content)
    if resolved_refs:
        skill_content += "\n\n--- Referenced Skills ---\n" + resolved_refs

    interactive_hint = ""
    if any(kw in skill_content.lower() for kw in ["interview", "ask the user"]):
        interactive_hint = "IMPORTANT: When the skill requires an interview or user input, you MUST stop and ask the user questions. Wait for their response before proceeding to the next phase.\n"

    rules_section = _load_rules(cwd=cwd)
    _write_task_state(cwd, cmd_name, cmd_args, skill_content)

    # Keep learned_feedback block as prefix, replace only the slash command part with skill content
    learned_prefix = ""
    if "<learned_feedback>" in full_task:
        learned_prefix = full_task.split("\n\n", 1)[0] + "\n\n"

    skill_message = (
        f"Execute this skill NOW. Do NOT explain -- start executing immediately using tools (bash, read_file, edit_file, etc.).\n"
        f"Follow the steps exactly as written. Do NOT run ls or explore first.\n"
        f"{interactive_hint}"
        f"Working directory: {cwd}{args_section}\n\n"
        f"IMPORTANT: A task state file has been created at `{cwd}/.hermit/task_state.md`. "
        f"Update this file as you complete each step (use edit_file). "
        f"If context is compressed, re-read this file to restore your progress.\n\n"
        f"{rules_section}"
        f"--- Project Config ---\n{_find_project_config(cwd)}\n\n"
        f"--- Skill ---\n{skill_content}"
    )
    return learned_prefix + skill_message
