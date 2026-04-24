"""hermit_agent profile-review CLI — outputs diff proposing guardrail removals/additions.

Usage:
    python -m hermit_agent.profile_review [--model MODEL] [--min-sessions N] [--apply]

Operation:
    1. Load session aggregates from ~/.hermit/metrics/sessions/
    2. Load current model profile
    3. Check guardrail list based on registry.yaml
    4. Calculate removal/addition proposals
    5. Output in diff format
    6. Update profile YAML notes field when --apply is used
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load_yaml_safe(path: Path) -> dict:
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_registry() -> dict:
    registry_path = Path(__file__).parent / "guardrails" / "registry.yaml"
    return _load_yaml_safe(registry_path)


def _load_profile(model_id: str | None) -> tuple[dict, Path | None]:
    """Loads model profile. Returns (profile_dict, path)."""
    defaults_dir = Path(__file__).parent / "profiles" / "defaults"
    user_dir = Path.home() / ".hermit" / "profiles"

    if model_id:
        slug = model_id.replace(":", "-").replace("/", "-")
        for base in (user_dir, defaults_dir):
            p = base / f"{slug}.yaml"
            if p.exists():
                return _load_yaml_safe(p), p

    unknown = defaults_dir / "unknown.yaml"
    if unknown.exists():
        return _load_yaml_safe(unknown), unknown
    return {}, None


def _format_diff(removal_candidates: list[str], addition_signals: dict, trigger_counts: dict, n: int) -> str:
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f" Guardrail Profile Review ({n} sessions)")
    lines.append(f"{'='*60}")

    lines.append(f"\ncompletion rate: {addition_signals['completion_rate']:.1%}  "
                 f"correction rate: {addition_signals['correction_rate']:.2f}/session")

    lines.append("\n[removal candidates] — 0 triggers + completion_rate ≥ 80%")
    if removal_candidates:
        for gid in removal_candidates:
            lines.append(f"  - {gid} ({trigger_counts.get(gid, 0)} triggers)")
        lines.append("\n  → removal candidate: consider adding 'removal review' to notes in the profile YAML.")
    else:
        lines.append("  none")

    lines.append("\n[addition review signals]")
    if addition_signals["needs_review"]:
        reasons = []
        if addition_signals["completion_rate"] < 0.6:
            reasons.append(f"low completion_rate ({addition_signals['completion_rate']:.1%} < 60%)")
        if addition_signals["correction_rate"] > 0.3:
            reasons.append(f"high correction_rate ({addition_signals['correction_rate']:.2f} > 0.3)")
        lines.append(f"  ⚠ {', '.join(reasons)}")
        lines.append("  → addition review: consider adding a new guardrail or strengthening existing conditions")
    else:
        lines.append("  none (within normal range)")

    lines.append(f"\n{'='*60}\n")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HermitAgent guardrail profile review")
    parser.add_argument("--model", default=None, help="Model ID (e.g. qwen3-coder:30b)")
    parser.add_argument("--min-sessions", type=int, default=1, help="Minimum session count (default 1)")
    parser.add_argument("--apply", action="store_true", help="Record removal candidates in profile YAML notes")
    parser.add_argument("--sessions-dir", default=None, help="Sessions directory (default ~/.hermit/metrics/sessions)")
    args = parser.parse_args(argv)

    from hermit_agent.metrics.aggregator import MetricsAggregator

    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else None
    agg = MetricsAggregator(sessions_dir=sessions_dir)
    sessions = agg.load_sessions()

    if len(sessions) < args.min_sessions:
        print(f"insufficient sessions: {len(sessions)} (need at least {args.min_sessions})")
        return 1

    registry = _load_registry()
    known_gids = list(registry.keys())
    trigger_counts = agg.trigger_counts(sessions)

    removal = agg.removal_candidates(sessions, known_gids)
    addition = agg.addition_signals(sessions)

    print(_format_diff(removal, addition, trigger_counts, len(sessions)))

    if args.apply and removal:
        profile, profile_path = _load_profile(args.model)
        if profile_path and profile_path.exists():
            import yaml
            notes: list = profile.setdefault("notes", [])
            for gid in removal:
                note = f"Removal review: {gid} (0 triggers, completion_rate {addition['completion_rate']:.1%})"
                if note not in notes:
                    notes.append(note)
            with open(profile_path, "w") as f:
                yaml.dump(profile, f, allow_unicode=True, sort_keys=False)
            print(f"Profile updated: {profile_path}")
        else:
            print("Profile file not found. --apply skipped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
