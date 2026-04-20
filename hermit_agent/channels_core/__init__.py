"""Shared pure helpers for HermitAgent channel/runtime surfaces.

This package is intentionally small and IO-light so bridge, gateway, and MCP
adapters can share semantics without moving their threading / transport /
session orchestration yet.
"""

from .approvals import ApprovalDecision, parse_permission_reply
from .event_adapters import (
    ChannelAction,
    bridge_messages_from_sse_event,
    channel_action_from_sse_event,
)

__all__ = [
    "ApprovalDecision",
    "ChannelAction",
    "bridge_messages_from_sse_event",
    "channel_action_from_sse_event",
    "parse_permission_reply",
]
