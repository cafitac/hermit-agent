from __future__ import annotations

import json

RESULT_CAP = 4000
HEAD_SIZE = 2000
TAIL_SIZE = 1000


def truncate_result(result: str, cap: int = RESULT_CAP) -> tuple[str, dict]:
    """Truncate long result strings with head+tail preservation."""
    if not isinstance(result, str):
        return result, {}
    if len(result) <= cap:
        return result, {}
    head = result[:HEAD_SIZE]
    tail = result[-TAIL_SIZE:]
    omitted = len(result) - HEAD_SIZE - TAIL_SIZE
    notice = (
        f"\n\n[... {omitted} chars omitted. "
        f"Use check_task(task_id, full=true) for full content ...]\n\n"
    )
    truncated = head + notice + tail
    metadata = {
        "truncated": True,
        "original_length": len(result),
        "head_size": HEAD_SIZE,
        "tail_size": TAIL_SIZE,
    }
    return truncated, metadata


def result_to_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
