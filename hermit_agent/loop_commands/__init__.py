"""Slash commands for HermitAgent — registered via @slash_command decorator.

All cmd_* functions take (agent: AgentLoop, args: str) -> str.
AgentLoop is imported lazily via TYPE_CHECKING to avoid circular imports.
"""
from __future__ import annotations

from ._registry import SLASH_COMMANDS, TRIGGER_AGENT, TRIGGER_AGENT_SINGLE, slash_command
from ._dispatch import handle_slash_command, _load_rules, _resolve_skill_references, _preprocess_slash_command
from . import _session  # noqa: F401 — registers session commands
from . import _config   # noqa: F401 — registers config commands
from . import _dev       # noqa: F401 — registers dev commands
from . import _workflow   # noqa: F401 — registers workflow commands
