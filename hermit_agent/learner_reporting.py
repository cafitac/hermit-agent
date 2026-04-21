"""Selection and reporting helpers for Learner."""

from __future__ import annotations

from pathlib import Path

from .learner_storage import parse_skill_file as _parse_skill_file


def _parser(parse_skill_file):
    return parse_skill_file or _parse_skill_file


def collect_active_skills(
    *,
    approved_dir: str,
    auto_learned_dir: str,
    parse_skill_file=None,
    context_keywords: list[str] | None = None,
) -> list[tuple[str, str]]:
    parser = _parser(parse_skill_file)
    result: list[tuple[str, str]] = []
    for search_dir in (approved_dir, auto_learned_dir):
        for path in Path(search_dir).glob('*.md'):
            parsed = parser(str(path))
            if not parsed:
                continue
            meta, body = parsed
            if context_keywords:
                haystack = ' '.join(meta.triggers + meta.scope).lower()
                if not any(keyword.lower() in haystack for keyword in context_keywords):
                    continue
            result.append((meta.name, body))
    return result


def build_status_report(
    *,
    pending_dir: str,
    approved_dir: str,
    deprecated_dir: str,
    auto_learned_dir: str,
    parse_skill_file=None,
) -> str:
    parser = _parser(parse_skill_file)
    approved = list(Path(approved_dir).glob('*.md'))
    lines = [
        f"[Learned Skills] pending:{len(list(Path(pending_dir).glob('*.md')))} "
        f"approved:{len(approved)} auto-learned:{len(list(Path(auto_learned_dir).glob('*.md')))} "
        f"deprecated:{len(list(Path(deprecated_dir).glob('*.md')))}",
    ]
    for path in approved:
        parsed = parser(str(path))
        if parsed:
            meta, _ = parsed
            lines.append(
                f"  • {meta.name}: {meta.success_rate:.0%} "
                f"({meta.success_count}✓/{meta.fail_count}✗, {meta.use_count}x)"
            )
    for path in Path(auto_learned_dir).glob('*.md'):
        parsed = parser(str(path))
        if parsed:
            meta, _ = parsed
            lines.append(f"  ✦ {meta.name} [auto] ({meta.use_count}x)")
    return '\n'.join(lines)
