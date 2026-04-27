"""Verification and lifecycle-evaluation helpers for Learner."""

from __future__ import annotations

import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path


def find_pytest_runner(cwd: str) -> str:
    venv_pytest = os.path.join(cwd, '.venv', 'bin', 'pytest')
    if os.path.exists(venv_pytest):
        return venv_pytest

    for root in [cwd] + [str(p) for p in Path(cwd).parents]:
        candidate = os.path.join(root, '.venv', 'bin', 'pytest')
        if os.path.exists(candidate):
            return candidate
    return venv_pytest


def run_pytest_check(cwd: str) -> tuple[bool, str]:
    runner = find_pytest_runner(cwd)
    try:
        result = subprocess.run(
            [runner, '-x', '-q', '--tb=short'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def resolve_verify_cmd(name: str, meta, rules: dict) -> str:
    if meta and meta.verify_cmd:
        return meta.verify_cmd
    if name in rules.get('by_name', {}):
        return rules['by_name'][name]
    if meta:
        trigger_str = ' '.join(meta.triggers).lower()
        for kw, kw_cmd in rules.get('by_trigger_keyword', {}).items():
            if kw.lower() in trigger_str:
                return kw_cmd
    return ''


def run_verify_command(cmd: str, cwd: str) -> bool | None:
    if not cmd:
        return None
    try:
        argv = shlex.split(cmd)
        if not argv:
            return None
        disallowed_tokens = {"|", "||", "&", "&&", ";", "<", ">", ">>"}
        if any(token in disallowed_tokens for token in argv):
            return None
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return None


def evaluate_cleanup_action(
    meta,
    *,
    min_uses_before_eval: int,
    deprecate_threshold: float,
    unused_days_threshold: int,
    now: datetime | None = None,
) -> tuple[str, str]:
    now = now or datetime.now()

    if meta.use_count >= min_uses_before_eval and meta.success_rate < deprecate_threshold:
        if meta.needs_review:
            if meta.use_count >= 10 and meta.success_rate < 0.3:
                return 'deprecate', (
                    f'success_rate {meta.success_rate:.0%} < 30% even after review (use={meta.use_count})'
                )
        else:
            return 'review', f'success_rate {meta.success_rate:.0%} < {deprecate_threshold:.0%}'

    if meta.last_used and meta.use_count > 0:
        try:
            last = datetime.strptime(meta.last_used, '%Y-%m-%d')
            days_unused = (now - last).days
            if days_unused > unused_days_threshold and meta.success_rate < 0.6:
                if meta.needs_review:
                    return 'deprecate', (
                        f'unused for {days_unused} days + success_rate {meta.success_rate:.0%} '
                        '(no improvement after review)'
                    )
                return 'review', f'unused for {days_unused} days + success_rate {meta.success_rate:.0%}'
        except Exception:
            return 'keep', ''

    return 'keep', ''
