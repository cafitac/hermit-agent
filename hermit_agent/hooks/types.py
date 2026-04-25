from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


HOOKS_CONFIG = os.path.expanduser("~/.hermit/hooks.json")


class HookEvent(Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    ON_START = "OnStart"
    ON_EXIT = "OnExit"


class HookAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"  # modify input/output


@dataclass
class HookResult:
    action: HookAction = HookAction.ALLOW
    message: str = ""
    modified_input: dict | None = None


@dataclass
class HookDefinition:
    """Hook definition loaded from ~/.hermit/hooks.json."""
    event: HookEvent
    tool: str  # tool name or "*"
    condition: str | None = None  # if condition (checks if contained in input)
    command: str | None = None  # shell command to execute
    action: HookAction = HookAction.ALLOW
    message: str = ""
