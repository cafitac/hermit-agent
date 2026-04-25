"""Session wrap — generates and saves a handoff artifact on session end.

Same purpose as Claude Code's `session-wrap` skill: leaves a markdown file with
summary + file changes + next steps so the following session can reconstruct context.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


_HANDOFF_DIR_NAME = os.path.join(".hermit", "handoffs")


def _gc_handoffs(handoffs_dir: Path, max_keep: int = 20) -> None:
    """Delete oldest `.md` files so at most `max_keep` remain."""
    try:
        files = sorted(
            (p for p in handoffs_dir.glob("*.md")),
            key=lambda p: p.stat().st_mtime,
        )
        excess = len(files) - max_keep
        for p in files[:excess] if excess > 0 else []:
            try:
                p.unlink()
            except OSError:
                pass
    except Exception:
        pass  # GC is best-effort


def build_handoff(
    summary: str,
    files_touched: list[str],
    next_steps: list[str],
) -> str:
    """Render 3-section markdown — Summary / Files / Next Steps."""
    lines = [
        f"# Session Handoff — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        summary.strip() or "(none)",
        "",
        "## Files",
    ]
    if files_touched:
        lines.extend(f"- {f}" for f in files_touched)
    else:
        lines.append("_(none recorded)_")
    lines.append("")
    lines.append("## Next Steps")
    if next_steps:
        lines.extend(f"- {s}" for s in next_steps)
    else:
        lines.append("_(none recorded)_")
    lines.append("")
    return "\n".join(lines)


def save_handoff(
    content: str,
    session_id: str | None = None,
    cwd: str | None = None,
    prefix: str | None = None,
) -> Path:
    cwd = cwd or os.getcwd()
    handoffs_dir = Path(cwd) / _HANDOFF_DIR_NAME
    handoffs_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    sid_suffix = session_id[:8] if session_id else ""

    if prefix:
        filename = f"{prefix}{ts}-{sid_suffix}.md" if sid_suffix else f"{prefix}{ts}.md"
    else:
        filename = f"{ts}_{session_id}.md" if session_id else f"{ts}.md"

    path = handoffs_dir / filename
    path.write_text(content)
    os.chmod(path, 0o600)
    _gc_handoffs(handoffs_dir, max_keep=20)
    return path


def build_handoff_rich(messages: list[dict], session_id: str | None = None) -> str:
    """Rule-based handoff generator (no LLM call). Extracts structured
    sections from raw messages for compact-fallback handoffs."""
    from ..context import _extract_file_paths  # reuse existing regex-based helper

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sid = session_id[:8] if session_id else "unknown"

    primary = ""
    for m in messages:
        if m.get("role") == "user" and not m.get("tool_call_id"):
            content = m.get("content", "")
            if isinstance(content, str):
                primary = content[:500]
            break

    user_msgs = []
    for m in messages:
        if m.get("role") == "user" and not m.get("tool_call_id"):
            c = m.get("content", "")
            if isinstance(c, str) and c.strip():
                user_msgs.append(f"- {c[:200].replace(chr(10), ' ')}")

    try:
        files = _extract_file_paths(messages, limit=10)
    except Exception:
        files = []

    current_work = []
    count = 0
    for m in reversed(messages):
        if count >= 3:
            break
        if m.get("role") in ("user", "assistant") and not m.get("tool_call_id"):
            c = m.get("content", "")
            if isinstance(c, str) and c.strip():
                current_work.append(f"- [{m['role']}] {c[:300].replace(chr(10), ' ')}")
                count += 1
    current_work.reverse()

    errors = []
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str) and any(k in c.lower() for k in ("traceback", "error:", "exception")):
            snippet = c[:200].replace("\n", " ")
            errors.append(f"- {snippet}")
            if len(errors) >= 5:
                break

    lines = [
        f"# Session Handoff (rich) — {now} — session {sid}",
        "",
        "## Primary Request",
        primary or "_(none recorded)_",
        "",
        "## All User Messages",
    ]
    lines.extend(user_msgs if user_msgs else ["_(none recorded)_"])
    lines.append("")
    lines.append("## Files Touched")
    if files:
        lines.extend(f"- {f}" for f in files)
    else:
        lines.append("_(none recorded)_")
    lines.append("")
    lines.append("## Current Work")
    lines.extend(current_work if current_work else ["_(none recorded)_"])
    lines.append("")
    lines.append("## Errors and Fixes")
    lines.extend(errors if errors else ["_(none recorded)_"])
    lines.append("")
    return "\n".join(lines)


def save_pre_compact_snapshot(
    messages: list[dict],
    session_id: str | None = None,
    cwd: str | None = None,
) -> Path:
    """Dump raw messages to `.hermit/handoffs/pre-compact-<ts>-<sid[:8]>.md`.
    Persisted before compact() mutates state so level 4 failure still has an artifact."""
    import json

    lines = ["# Pre-compact raw snapshot", ""]
    lines.append(f"Total messages: {len(messages)}")
    lines.append("")
    for i, m in enumerate(messages):
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)[:1000]
        lines.append(f"## [{i}] {role}")
        lines.append(content[:2000])
        lines.append("")

    return save_handoff(
        "\n".join(lines),
        session_id=session_id,
        cwd=cwd,
        prefix="pre-compact-",
    )


def _pick_latest_handoff(handoffs_dir: Path, consumed: set[str]) -> Path | None:
    """Select the most recent non-consumed handoff.

    Priority: auto-compact-*.md (structured 9-section) > pre-compact-*.md (raw fallback)
    > shutdown handoffs (any other *.md). Within each tier, sorted by filename reverse
    (which matches timestamp order since all names embed YYYYMMDD-HHMMSS).
    """
    if not handoffs_dir.is_dir():
        return None

    groups = [
        sorted(handoffs_dir.glob("auto-compact-*.md"), reverse=True),
        sorted(handoffs_dir.glob("pre-compact-*.md"), reverse=True),
    ]
    # Catch-all for shutdown handoffs: any .md not already matched by above two patterns
    seen = {p for g in groups for p in g}
    misc = sorted(
        (p for p in handoffs_dir.glob("*.md") if p not in seen),
        reverse=True,
    )
    groups.append(misc)

    for group in groups:
        for path in group:
            if path.name in consumed:
                continue
            return path
    return None


def _load_consumed(handoffs_dir: Path) -> set[str]:
    """Return set of filenames previously consumed (seed-injected).
    Missing file -> empty set; malformed lines -> skipped."""
    import json

    consumed_file = handoffs_dir / ".consumed"
    if not consumed_file.is_file():
        return set()

    result: set[str] = set()
    try:
        with consumed_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    name = rec.get("file")
                    if isinstance(name, str):
                        result.add(name)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return result


def _mark_consumed(handoffs_dir: Path, file_name: str) -> None:
    """Append a consumption record to `.consumed` (JSONL, atomic-write)."""
    import json
    from datetime import datetime

    try:
        handoffs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    record = json.dumps({
        "file": file_name,
        "consumed_at": datetime.now().isoformat(timespec="seconds"),
    })
    consumed_file = handoffs_dir / ".consumed"
    try:
        with consumed_file.open("a", encoding="utf-8") as f:
            f.write(record + "\n")
    except OSError:
        pass


_FALSY = {"0", "false", "no", "off"}


def maybe_auto_wrap(
    cwd: str,
    session_id: str | None,
    modified_files: list[str],
    messages: list[dict] | None = None,
) -> Path | None:
    """Save a handoff artifact on shutdown.

    Default is ON: writes unless `HERMIT_AUTO_WRAP` is explicitly set to
    one of {0, false, no, off}. Skipped when `modified_files` is empty.

    When `messages` is provided, the handoff uses `build_handoff_rich`
    (structured, 5-section). Otherwise falls back to the legacy 3-section
    `build_handoff` stub for backward compatibility.
    """
    raw = os.environ.get("HERMIT_AUTO_WRAP", "").lower()
    if raw in _FALSY:
        return None
    if not modified_files:
        return None

    if messages:
        content = build_handoff_rich(messages=messages, session_id=session_id)
    else:
        summary = f"Auto-wrap on shutdown — {len(modified_files)} file(s) changed."
        content = build_handoff(
            summary=summary,
            files_touched=sorted(modified_files),
            next_steps=[],
        )
    return save_handoff(content=content, session_id=session_id, cwd=cwd)
