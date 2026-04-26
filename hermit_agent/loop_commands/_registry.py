"""Slash command registry — decorator and constants."""
from __future__ import annotations

SLASH_COMMANDS: dict = {}
TRIGGER_AGENT = "__trigger_agent__"
TRIGGER_AGENT_SINGLE = "__trigger_agent_single__"  # Interactive mode: run 1 turn only


def slash_command(name: str, description: str):
    def decorator(func):
        SLASH_COMMANDS[name] = {"func": func, "description": description}
        return func
    return decorator
