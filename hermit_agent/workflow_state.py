"""Workflow state persistence.

Saves, loads, and deletes per-mode state as JSON files.
Storage path: ~/.hermit/state/{mode}-state.json
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


STATE_DIR = os.path.expanduser("~/.hermit/state")


@dataclass
class WorkflowState:
    mode: str  # autopilot, ralph, ultraqa
    task_id: str
    phase: str = ""
    status: str = "running"  # running, completed, failed, cancelled
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "task_id": self.task_id,
            "phase": self.phase,
            "status": self.status,
            "data": self.data,
        }

    @staticmethod
    def from_dict(d: dict) -> WorkflowState:
        return WorkflowState(
            mode=d["mode"],
            task_id=d["task_id"],
            phase=d.get("phase", ""),
            status=d.get("status", "running"),
            data=d.get("data", {}),
        )


def _state_path(mode: str) -> str:
    return os.path.join(STATE_DIR, f"{mode}-state.json")


def save_workflow_state(state: WorkflowState) -> str:
    """Save workflow state to disk. Returns the save path."""
    os.makedirs(STATE_DIR, exist_ok=True)
    path = _state_path(state.mode)
    with open(path, "w") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def load_workflow_state(mode: str) -> WorkflowState | None:
    """Load workflow state from disk. Returns None if not found."""
    path = _state_path(mode)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return WorkflowState.from_dict(json.load(f))
    except Exception:
        return None


def delete_workflow_state(mode: str) -> bool:
    """Delete workflow state file. Returns True on success."""
    path = _state_path(mode)
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return False


def can_resume(mode: str) -> bool:
    """Check whether a resumable state exists."""
    state = load_workflow_state(mode)
    return state is not None and state.status == "running"


def get_resume_info(mode: str) -> str | None:
    """Return resume info string. Returns None if not available."""
    state = load_workflow_state(mode)
    if state is None or state.status != "running":
        return None
    phase_info = f" at phase '{state.phase}'" if state.phase else ""
    return f"[{mode}] task_id={state.task_id}{phase_info}"
