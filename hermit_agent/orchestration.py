"""Conservative orchestration policy for Hermit executor tasks.

The policy chooses *when* extra agents are justified.  It never permits
parallel write agents: quality and repository safety matter more than reducing
wall-clock time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_ORCHESTRATION_MODES = ("single", "auto")
_COMPLEXITY_SIGNALS = (
    "architecture",
    "migration",
    "refactor",
    "security",
    "authentication",
    "authorization",
    "concurrency",
    "database schema",
    "breaking change",
)

PLANNER_SYSTEM_PROMPT = (
    "You are Hermit's planning agent. Inspect the repository with read-only tools and produce a concise, "
    "testable implementation plan. Do not modify files and do not guess about unseen code."
)
REVIEWER_SYSTEM_PROMPT = (
    "You are Hermit's final quality reviewer. Inspect the relevant repository files with read-only tools. "
    "Check correctness, regressions, security, and test coverage. Your first line must be exactly "
    "VERDICT: PASS or VERDICT: NEEDS_REVIEW. Use NEEDS_REVIEW for any likely P1/P2 issue. Do not modify files."
)


@dataclass(frozen=True)
class OrchestrationPlan:
    requested_mode: str
    stages: tuple[str, ...]
    quality_gate: bool
    max_agents: int
    allow_parallel_writes: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_mode": self.requested_mode,
            "stages": list(self.stages),
            "quality_gate": self.quality_gate,
            "max_agents": self.max_agents,
            "allow_parallel_writes": self.allow_parallel_writes,
            "reason": self.reason,
        }


def resolve_orchestration(task: str, cfg: dict[str, Any], *, mode: str | None = None) -> OrchestrationPlan:
    """Select a quality-preserving execution plan.

    ``single`` is the default, preserving today's lowest-cost behavior.  In
    ``auto`` mode only tasks with clear complexity signals receive read-only
    planning and review around the one writing executor.
    """
    settings = cfg.get("orchestration")
    settings = settings if isinstance(settings, dict) else {}
    requested_mode = str(mode or settings.get("mode") or "single").strip().lower()
    if requested_mode not in VALID_ORCHESTRATION_MODES:
        requested_mode = "single"

    max_agents = max(1, min(int(settings.get("max_agents", 3) or 3), 3))
    allow_parallel_writes = bool(settings.get("allow_parallel_writes", False))
    # This product contract intentionally never enables competing writers.
    allow_parallel_writes = False

    normalized = (task or "").casefold()
    complex_task = len(normalized) >= 900 or any(signal in normalized for signal in _COMPLEXITY_SIGNALS)
    if requested_mode == "auto" and complex_task and max_agents >= 3:
        return OrchestrationPlan(
            requested_mode="auto",
            stages=("planner", "executor", "reviewer"),
            quality_gate=True,
            max_agents=max_agents,
            allow_parallel_writes=allow_parallel_writes,
            reason="complex task requires a read-only plan and review",
        )

    reason = "default low-cost execution" if requested_mode == "single" else "task does not justify extra agent cost"
    return OrchestrationPlan(
        requested_mode=requested_mode,
        stages=("executor",),
        quality_gate=False,
        max_agents=max_agents,
        allow_parallel_writes=allow_parallel_writes,
        reason=reason,
    )


def review_requires_attention(review: str) -> bool:
    """Fail closed when a reviewer is inconclusive or reports a material issue."""
    first_line = (review or "").strip().splitlines()[0:1]
    if not first_line:
        return True
    verdict = first_line[0].strip().upper()
    return verdict != "VERDICT: PASS"
