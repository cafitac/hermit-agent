from __future__ import annotations

from dataclasses import dataclass


def test_build_bridge_commands_combines_slash_commands_and_skills(monkeypatch):
    import hermit_agent.bridge_commands as bridge_commands

    @dataclass
    class _Skill:
        name: str
        description: str

    class _Registry:
        def list_skills(self):
            return [_Skill(name="review", description="Review code"), _Skill(name="help", description="Skill help")]

    monkeypatch.setattr(
        "hermit_agent.loop.SLASH_COMMANDS",
        {
            "help": {"description": "Get help"},
            "compact": {"description": "Compact context"},
        },
    )
    monkeypatch.setattr("hermit_agent.skills.SkillRegistry", _Registry)

    commands = bridge_commands.build_bridge_commands()

    assert commands["/help"] == "Get help"
    assert commands["/compact"] == "Compact context"
    assert commands["/review"] == "[skill] Review code"


def test_build_bridge_commands_tolerates_loader_failures(monkeypatch):
    import hermit_agent.bridge_commands as bridge_commands

    class _BrokenRegistry:
        def __init__(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("hermit_agent.skills.SkillRegistry", _BrokenRegistry)
    monkeypatch.setattr("hermit_agent.loop.SLASH_COMMANDS", {"help": {"description": "Get help"}})

    assert bridge_commands.build_bridge_commands() == {"/help": "Get help"}
