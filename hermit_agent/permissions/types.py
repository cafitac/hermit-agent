from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionBehavior(Enum):
    """4 permission behaviors. Claude Code's PermissionResult pattern."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    PASSTHROUGH = "passthrough"  # Delegate to the general permission system


@dataclass
class PermissionResult:
    """3-step decision result."""
    behavior: PermissionBehavior
    message: str = ""
    updated_input: dict | None = None


class PermissionMode(Enum):
    ASK = "ask"
    ALLOW_READ = "allow_read"
    ACCEPT_EDITS = "accept_edits"
    YOLO = "yolo"
    DONT_ASK = "dont_ask"
    PLAN = "plan"
