"""UltraQA — QA cycling workflow.

test → architect diagnosis → fix → re-verify, up to 5 iterations.
Early exit when the same error is detected 3 times.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm_client import LLMClientBase


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class CycleRecord:
    cycle: int
    errors: list[str]
    fix_attempted: bool


@dataclass
class UltraQAState:
    task_id: str
    test_command: str
    cwd: str
    max_cycles: int = 5
    current_cycle: int = 0
    status: str = "running"   # running / passed / failed / cancelled
    error_history: list[CycleRecord] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _state_path(task_id: str) -> str:
        state_dir = os.path.expanduser("~/.hermit/state")
        os.makedirs(state_dir, exist_ok=True)
        return os.path.join(state_dir, f"ultraqa-{task_id}.json")

    def save(self) -> None:
        data = {
            "task_id": self.task_id,
            "test_command": self.test_command,
            "cwd": self.cwd,
            "max_cycles": self.max_cycles,
            "current_cycle": self.current_cycle,
            "status": self.status,
            "error_history": [
                {"cycle": r.cycle, "errors": r.errors, "fix_attempted": r.fix_attempted}
                for r in self.error_history
            ],
        }
        with open(self._state_path(self.task_id), "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, task_id: str) -> "UltraQAState | None":
        path = cls._state_path(task_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            state = cls(
                task_id=data["task_id"],
                test_command=data["test_command"],
                cwd=data["cwd"],
                max_cycles=data.get("max_cycles", 5),
                current_cycle=data.get("current_cycle", 0),
                status=data.get("status", "running"),
            )
            for r in data.get("error_history", []):
                state.error_history.append(
                    CycleRecord(
                        cycle=r["cycle"],
                        errors=r["errors"],
                        fix_attempted=r["fix_attempted"],
                    )
                )
            return state
        except Exception:
            return None


def save_state(state: UltraQAState) -> None:
    """Save UltraQA state to disk (helper for external callers)."""
    state.save()


def find_active_ultraqa() -> UltraQAState | None:
    """Search for an active UltraQA state file."""
    state_dir = os.path.expanduser("~/.hermit/state")
    if not os.path.exists(state_dir):
        return None
    for fname in os.listdir(state_dir):
        if not fname.startswith("ultraqa-") or not fname.endswith(".json"):
            continue
        path = os.path.join(state_dir, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("status") == "running":
                task_id = data.get("task_id", "")
                return UltraQAState.load(task_id)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# UltraQA
# ---------------------------------------------------------------------------

_ARCHITECT_SYSTEM = (
    "You are a senior architect. Read-only mode — do NOT modify any files. "
    "Analyze the test failures and identify the root cause. "
    "Return a concise diagnosis with: "
    "1. Root cause (file:line if possible). "
    "2. Specific fix recommendation."
)

_EXECUTOR_SYSTEM = (
    "You are an executor. Apply the fix described in the diagnosis. "
    "Read the relevant files first, then make the minimal necessary edits. "
    "After fixing, do NOT re-run tests — the QA loop will do that."
)


class UltraQA:
    """QA cycling workflow."""

    def __init__(self, llm: "LLMClientBase", tools: list, cwd: str, emitter=None):
        self.llm = llm
        self.tools = tools
        self.cwd = os.path.abspath(cwd)
        if emitter is None:
            from .events import AgentEventEmitter
            emitter = AgentEventEmitter()
        self.emitter = emitter

    # ------------------------------------------------------------------
    # Test command detection
    # ------------------------------------------------------------------

    def detect_test_command(self) -> str:
        """Auto-detect test command from project config files."""
        checks = [
            (os.path.join(self.cwd, "pytest.ini"), "pytest"),
            (os.path.join(self.cwd, "setup.cfg"), "pytest"),
            (os.path.join(self.cwd, "pyproject.toml"), "pytest"),
            (os.path.join(self.cwd, "tox.ini"), "tox"),
        ]
        for path, cmd in checks:
            if os.path.exists(path):
                return cmd

        package_json = os.path.join(self.cwd, "package.json")
        if os.path.exists(package_json):
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                if "test" in pkg.get("scripts", {}):
                    return "npm test"
            except Exception:
                pass

        makefile = os.path.join(self.cwd, "Makefile")
        if os.path.exists(makefile):
            try:
                with open(makefile) as f:
                    content = f.read()
                if "^test:" in content or "\ntest:" in content:
                    return "make test"
            except Exception:
                pass

        # Fallback: look for test files
        for root, _dirs, files in os.walk(self.cwd):
            for fn in files:
                if fn.startswith("test_") and fn.endswith(".py"):
                    return "pytest"
            break  # only check top-level

        return "pytest"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, test_command: str | None = None) -> UltraQAState:
        """Initialize QA state, auto-detect test command if not provided."""
        cmd = test_command or self.detect_test_command()
        state = UltraQAState(
            task_id=uuid.uuid4().hex[:8],
            test_command=cmd,
            cwd=self.cwd,
        )
        state.save()
        return state

    def run_cycle(self, state: UltraQAState) -> bool:
        """Single QA cycle.

        Returns True if another cycle is needed, False if tests passed.
        """
        self.emitter.progress(f"[UltraQA cycle {state.current_cycle}/{state.max_cycles}]")

        # 1. Run tests
        errors = self._run_tests(state.test_command)

        if not errors:
            self.emitter.progress("[UltraQA] All tests passed.")
            return False  # done

        self.emitter.progress(f"[UltraQA] {len(errors)} failure(s) detected.")
        record = CycleRecord(cycle=state.current_cycle, errors=errors, fix_attempted=False)

        # 2. Diagnose
        diagnosis = self._diagnose(errors)
        self.emitter.progress("[UltraQA] Diagnosis complete.")

        # 3. Fix
        self._fix(diagnosis, errors)
        record.fix_attempted = True
        state.error_history.append(record)

        return True  # continue

    def run_loop(self, state: UltraQAState) -> str:
        """Main QA loop. Runs cycles until pass, stall, or max cycles."""
        start_time = time.time()

        while state.current_cycle < state.max_cycles and state.status == "running":
            state.current_cycle += 1
            should_continue = self.run_cycle(state)
            state.save()

            if not should_continue:
                state.status = "passed"
                break

            if self._detect_stall(state):
                self.emitter.progress("[UltraQA] Stall detected (same error 3+ times). Stopping.")
                state.status = "failed"
                break

        # If we exhausted cycles without passing
        if state.status == "running":
            state.status = "failed"

        elapsed = time.time() - start_time
        state.save()
        return self._build_summary(state, elapsed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_tests(self, test_command: str) -> list[str]:
        """Run tests and parse failures. Returns list of error strings."""
        try:
            result = subprocess.run(
                test_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=300,
            )
            if result.returncode == 0:
                return []

            output = result.stdout + result.stderr
            return self._parse_failures(output)
        except subprocess.TimeoutExpired:
            return ["Test run timed out after 300s"]
        except Exception as e:
            return [f"Test execution error: {e}"]

    def _parse_failures(self, output: str) -> list[str]:
        """Extract failure messages from test output."""
        failures = []
        lines = output.splitlines()

        # Collect FAILED lines (pytest style)
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
                failures.append(stripped[:300])

        # Collect assertion/error blocks
        in_block = False
        block_lines: list[str] = []
        for line in lines:
            if line.startswith("E ") or line.startswith("  E "):
                in_block = True
                block_lines.append(line.strip())
            elif in_block and (line.startswith("_") or line.startswith("=")):
                if block_lines:
                    failures.append(" ".join(block_lines[:5]))
                    block_lines = []
                in_block = False

        if not failures:
            # Fallback: last 20 non-empty lines
            tail = [line for line in lines if line.strip()][-20:]
            failures = ["\n".join(tail[:10])]

        return failures[:10]  # cap at 10

    def _diagnose(self, errors: list[str]) -> str:
        """Architect-style read-only diagnosis."""
        from .loop import AgentLoop
        from .permissions import PermissionMode
        from .auto_agents import _filter_readonly_tools

        readonly_tools = _filter_readonly_tools(self.tools)
        agent = AgentLoop(
            llm=self.llm,
            tools=readonly_tools,
            cwd=self.cwd,
            permission_mode=PermissionMode.YOLO,
            system_prompt=_ARCHITECT_SYSTEM,
        )
        agent.MAX_TURNS = 10
        agent.streaming = False

        error_text = "\n".join(errors)
        prompt = (
            f"Diagnose these test failures:\n\n{error_text}\n\n"
            "Read relevant source files to identify the root cause. "
            "Return a concise diagnosis with root cause and fix recommendation."
        )
        return agent.run(prompt)

    def _fix(self, diagnosis: str, errors: list[str]) -> str:
        """Executor-style fix agent."""
        from .loop import AgentLoop
        from .permissions import PermissionMode

        agent = AgentLoop(
            llm=self.llm,
            tools=self.tools,
            cwd=self.cwd,
            permission_mode=PermissionMode.YOLO,
            system_prompt=_EXECUTOR_SYSTEM,
        )
        agent.MAX_TURNS = 20
        agent.streaming = False

        error_text = "\n".join(errors)
        prompt = (
            f"Apply the following fix to resolve test failures.\n\n"
            f"Diagnosis:\n{diagnosis}\n\n"
            f"Test failures:\n{error_text}\n\n"
            "Read the relevant files first, then make the minimal edits to fix the failures."
        )
        return agent.run(prompt)

    def _detect_stall(self, state: UltraQAState) -> bool:
        """Same error appearing 3+ consecutive times → stalled."""
        if len(state.error_history) < 3:
            return False

        last_three = state.error_history[-3:]
        # Normalize error sets for comparison
        error_sets = [frozenset(r.errors) for r in last_three]
        return error_sets[0] == error_sets[1] == error_sets[2]

    def _build_summary(self, state: UltraQAState, elapsed: float) -> str:
        status_color = "\033[32m" if state.status == "passed" else "\033[31m"
        reset = "\033[0m"
        lines = [
            f"\n{status_color}[UltraQA] {state.status.upper()}{reset}",
            f"Cycles: {state.current_cycle}/{state.max_cycles}",
            f"Elapsed: {elapsed:.1f}s",
            f"Test command: {state.test_command}",
        ]
        if state.error_history:
            lines.append(f"Error cycles: {len(state.error_history)}")
            for r in state.error_history:
                fix_str = "fixed" if r.fix_attempted else "no fix"
                lines.append(f"  Cycle {r.cycle}: {len(r.errors)} failure(s) [{fix_str}]")
        return "\n".join(lines)
