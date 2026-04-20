from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalDecision:
    allow: bool
    escalate_to_yolo: bool = False


def parse_permission_reply(answer: str | None) -> ApprovalDecision:
    """Parse Hermit approval replies while preserving current semantics."""
    normalized = (answer or "").strip().lower()
    if "yolo" in normalized or "always" in normalized or normalized == "2":
        return ApprovalDecision(allow=True, escalate_to_yolo=True)
    if normalized == "no" or normalized.startswith("no"):
        return ApprovalDecision(allow=False, escalate_to_yolo=False)
    allow_once = (
        normalized in ("", "y", "yes", "1")
        or "yes" in normalized
        or "once" in normalized
    )
    return ApprovalDecision(allow=allow_once, escalate_to_yolo=False)
