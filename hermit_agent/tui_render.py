from __future__ import annotations

import re

CONTROL_CHARS_RE = re.compile(r"[\u0000-\u001f\u007f-\u009f]")
ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def sanitize_dynamic_text(value: str) -> str:
    return CONTROL_CHARS_RE.sub("", strip_ansi(value))


def strip_ansi(value: str) -> str:
    return ANSI_SGR_RE.sub("", value)


def visible_length(value: str) -> int:
    return len(strip_ansi(value))


def ellipsize_segment(value: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    sanitized = sanitize_dynamic_text(value)
    if visible_length(sanitized) <= max_width:
        return sanitized

    plain = strip_ansi(sanitized)
    if len(plain) <= max_width:
        return plain
    if max_width <= 1:
        return "…"
    if max_width <= 4:
        return f"{plain[: max(0, max_width - 1)]}…"

    head = max(1, (max_width - 1 + 1) // 2)
    tail = max(1, (max_width - 1) // 2)
    return f"{plain[:head]}…{plain[-tail:]}"


def compact_count_label(label: str, value: int) -> str:
    if value >= 1_000_000:
        formatted = f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        formatted = f"{value / 1_000:.1f}k"
    else:
        formatted = str(value)
    return f"{label}:{formatted}"
