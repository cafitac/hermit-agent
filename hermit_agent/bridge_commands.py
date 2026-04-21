from __future__ import annotations


def build_bridge_commands() -> dict[str, str]:
    """Load slash commands + skills for TUI autocomplete/help surfaces."""
    commands: dict[str, str] = {}
    try:
        from .loop import SLASH_COMMANDS

        commands = {f"/{k}": v["description"] for k, v in sorted(SLASH_COMMANDS.items())}
    except Exception:
        pass
    try:
        from .skills import SkillRegistry

        registry = SkillRegistry()
        for skill in registry.list_skills():
            key = f"/{skill.name}"
            if key not in commands:
                commands[key] = f"[skill] {skill.description}"
    except Exception:
        pass
    return commands
