"""Ralph — Persistence loop that keeps working until task completion.

OMC ralph pattern: PRD-based iterative execution + architect verification.
"Never stops until complete."

Usage: /ralph <task description>
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal


# ─── State ────────────────────────────────────────────────

RALPH_STATE_DIR = os.path.expanduser("~/.hermit/state")


@dataclass
class VerificationResult:
    iteration: int
    passed: bool
    feedback: list[dict]  # [{criterion, passed, feedback}]


@dataclass
class RalphState:
    """Tracks Ralph execution state."""
    task_id: str
    task_description: str
    acceptance_criteria: list[str]
    iteration: int = 0
    max_iterations: int = 20
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    progress_log: list[str] = field(default_factory=list)
    verification_results: list[dict] = field(default_factory=list)  # serialized VerificationResult


def _state_path(task_id: str) -> str:
    return os.path.join(RALPH_STATE_DIR, f"ralph-{task_id}.json")


def save_state(state: RalphState) -> None:
    """Save Ralph state to disk."""
    os.makedirs(RALPH_STATE_DIR, exist_ok=True)
    path = _state_path(state.task_id)
    with open(path, "w") as f:
        json.dump(asdict(state), f, ensure_ascii=False, indent=2)


def load_state(task_id: str) -> RalphState | None:
    """Restore Ralph state from disk."""
    path = _state_path(task_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return RalphState(**data)
    except Exception:
        return None


def find_active_ralph() -> RalphState | None:
    """Search for an active Ralph state file."""
    if not os.path.exists(RALPH_STATE_DIR):
        return None
    for fname in os.listdir(RALPH_STATE_DIR):
        if not fname.startswith("ralph-") or not fname.endswith(".json"):
            continue
        path = os.path.join(RALPH_STATE_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("status") == "running":
                return RalphState(**data)
        except Exception:
            continue
    return None


# ─── System prompts ────────────────────────────────────────

_EXECUTOR_SYSTEM = (
    "You are a persistence executor. Work on the assigned task and make real progress. "
    "Use all available tools (read_file, edit_file, write_file, bash, glob, grep) to implement changes. "
    "IMPORTANT rules:\n"
    "- Create all files in the current working directory (cwd), NOT in scratchpad.\n"
    "- Always use relative paths (e.g. 'main.py', 'src/app.py').\n"
    "- You MUST read_file before edit_file.\n"
    "- For Python projects: create a venv with 'python3 -m venv venv', then use 'venv/bin/pip' and 'venv/bin/python'.\n"
    "- NEVER use paths with spaces directly in bash. Use quotes: '\"path with spaces\"'.\n"
    "- NEVER use Python package names as project/app/directory names (django, test, api, config, etc.). Use specific names like todo_project, todo_api.\n"
    "- Be thorough. Check your work. Run tests if they exist."
)

_VERIFIER_SYSTEM = (
    "You are a strict verifier. Check each acceptance criterion thoroughly. "
    "Use ALL available tools: read_file to check code, bash to run tests/commands, glob to find files. "
    "For execution criteria (e.g. 'tests pass', 'server starts'), actually RUN the command and check output. "
    "Do NOT assume something works just because the file exists — verify by execution. "
    "Be strict: if a criterion says 'tests pass' but there are import errors, it FAILS. "
    "For each criterion, report: criterion text, passed (true/false), and specific feedback with evidence. "
    "Return a JSON object: "
    '{"all_passed": bool, "results": [{"criterion": str, "passed": bool, "feedback": str}]}'
)


# ─── Prompts ───────────────────────────────────────────────

_CRITERIA_PROMPT = """Given this task, list 8-15 specific, testable acceptance criteria.

Criteria MUST include:
1. Project structure: required files/directories exist (settings, configs, package.json, etc.)
2. Functionality: each feature works correctly (not just "file exists" but "API returns 200")
3. Execution: the project actually runs (server starts, tests pass, build succeeds)
4. Integration: components connect properly (frontend calls backend, auth protects routes)
5. Quality: tests exist and pass, no import errors, type checks pass

BAD criteria (too vague): "TodoViewSet exists in views.py"
GOOD criteria: "Running 'python manage.py test' passes all tests including CRUD operations"

Task: {task}

Return ONLY a JSON array of strings, no explanation:
["criterion 1", "criterion 2", ...]"""

_EXECUTOR_PROMPT = """Work on the following task. Focus on acceptance criteria that are not yet met.

Task: {task}

Acceptance criteria still to complete:
{pending_criteria}

Iteration {iteration}/{max_iterations}. Previous progress:
{progress_log}

Make real, concrete progress. Implement the code changes needed to satisfy the criteria."""

_VERIFIER_PROMPT = """Verify whether the following acceptance criteria are met for this task.

Task: {task}

Acceptance criteria to check:
{criteria}

Read the relevant files and check each criterion. Return ONLY a JSON object:
{{"all_passed": true/false, "results": [{{"criterion": "...", "passed": true/false, "feedback": "..."}}]}}"""


# ─── Ralph ─────────────────────────────────────────────────

class Ralph:
    """Ralph persistence loop executor."""

    def __init__(self, llm, tools: list, cwd: str, emitter=None):
        self.llm = llm
        self.tools = tools
        self.cwd = cwd
        if emitter is None:
            from .events import AgentEventEmitter
            emitter = AgentEventEmitter()
        self.emitter = emitter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, task: str) -> RalphState:
        """1. Parse task into acceptance criteria using LLM
           2. Initialize state (does not start loop)"""
        task_id = uuid.uuid4().hex[:8]
        criteria = self._extract_criteria(task)

        state = RalphState(
            task_id=task_id,
            task_description=task,
            acceptance_criteria=criteria,
        )
        save_state(state)
        return state

    def run_loop(self, state: RalphState) -> str:
        """Main persistence loop. Runs until done, failed, or cancelled."""
        self.emitter.progress(f"[Ralph] Starting: {state.task_description[:60]}")
        self.emitter.progress(f"[Ralph] Criteria ({len(state.acceptance_criteria)}):")
        for i, c in enumerate(state.acceptance_criteria, 1):
            self.emitter.progress(f"  {i}. {c}")

        while state.iteration < state.max_iterations and state.status == "running":
            state.iteration += 1

            # btw: check if the user sent additional messages during execution
            if hasattr(self, '_parent_agent') and self._parent_agent.pending_user_messages:
                for user_msg in self._parent_agent.pending_user_messages:
                    self.emitter.progress(f"[btw] applied: {user_msg[:60]}")
                    state.task_description += f"\n\nAdditional requirement: {user_msg}"
                self._parent_agent.pending_user_messages.clear()

            self.emitter.progress(f"[Ralph iteration {state.iteration}/{state.max_iterations}]")

            should_continue = self.run_iteration(state)
            save_state(state)

            if not should_continue:
                state.status = "completed"
                save_state(state)
                break

            if self._is_stalled(state):
                self.emitter.progress("[Ralph: stalled — same failures 3 iterations. Stopping.]")
                state.status = "failed"
                save_state(state)
                break

        if state.status == "running":
            # Hit max_iterations without completion
            state.status = "failed"

        # Delete state file on completion/failure (prevent disk accumulation)
        summary = self._generate_summary(state)
        path = _state_path(state.task_id)
        try:
            os.remove(path)
            self.emitter.progress(f"[Ralph] cleaning state file: {state.task_id}")
        except OSError:
            pass

        return summary

    def run_iteration(self, state: RalphState) -> bool:
        """Single iteration: execute → verify → decide continue/stop.
        Returns True if should continue, False if all criteria are met."""
        pending = self._pending_criteria(state)

        # 1. Execute sub-agent
        self._run_executor(state, pending)

        # 2. Verify
        verification = self.verify(state)
        state.verification_results.append(asdict(verification))

        passed_count = sum(1 for r in verification.feedback if r.get("passed"))
        total = len(verification.feedback)
        progress_msg = (
            f"Iteration {state.iteration}: {passed_count}/{total} criteria passed"
        )
        state.progress_log.append(progress_msg)
        self.emitter.progress(f"[Ralph] {progress_msg}")

        for r in verification.feedback:
            status_icon = "+" if r.get("passed") else "-"
            self.emitter.progress(f"  [{status_icon}] {r.get('criterion', '')[:60]}")
            if not r.get("passed") and r.get("feedback"):
                self.emitter.progress(f"      {r['feedback'][:100]}")

        return not verification.passed

    def verify(self, state: RalphState) -> VerificationResult:
        """Architect verification — check each acceptance criterion.
        Returns VerificationResult with per-criterion results."""
        from .loop import AgentLoop
        from .permissions import PermissionMode

        criteria_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(state.acceptance_criteria))
        prompt = _VERIFIER_PROMPT.format(
            task=state.task_description,
            criteria=criteria_text,
        )

        try:
            # provide all tools to the verifier — needed for running tests, verifying server startup, etc.
            agent = AgentLoop(
                llm=self.llm,
                tools=self.tools,
                cwd=self.cwd,
                permission_mode=PermissionMode.YOLO,
                system_prompt=_VERIFIER_SYSTEM,
            )
            agent.MAX_TURNS = 15
            agent.streaming = True
            agent.emitter = self.emitter
            raw = agent.run(prompt)

            # Parse JSON from response
            results = self._parse_verification_json(raw, state.acceptance_criteria)
            all_passed = all(r.get("passed", False) for r in results)
            return VerificationResult(
                iteration=state.iteration,
                passed=all_passed,
                feedback=results,
            )
        except Exception as e:
            # Verification failure — treat all criteria as failing
            results = [
                {"criterion": c, "passed": False, "feedback": f"Verification error: {e}"}
                for c in state.acceptance_criteria
            ]
            return VerificationResult(
                iteration=state.iteration,
                passed=False,
                feedback=results,
            )

    def cancel(self, state: RalphState) -> None:
        """Cancel active ralph execution."""
        state.status = "cancelled"
        save_state(state)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_criteria(self, task: str) -> list[str]:
        """Use LLM to extract testable acceptance criteria from task description."""
        prompt = _CRITERIA_PROMPT.format(task=task)
        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You extract acceptance criteria. Return ONLY a JSON array.",
                temperature=0.0,
            )
            if response and response.content:
                content = response.content.strip()
                # Strip markdown code fences if present
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(
                        line for line in lines if not line.startswith("```")
                    ).strip()
                criteria = json.loads(content)
                if isinstance(criteria, list) and criteria:
                    return [str(c) for c in criteria[:7]]
        except Exception:
            pass
        # Fallback: single criterion
        return [f"Task completed: {task[:100]}"]

    def _run_executor(self, state: RalphState, pending: list[str]) -> str:
        """Run sub-agent to make progress on pending criteria."""
        from .loop import AgentLoop
        from .permissions import PermissionMode

        progress_text = "\n".join(state.progress_log[-3:]) if state.progress_log else "First iteration."
        pending_text = "\n".join(f"- {c}" for c in pending)

        prompt = _EXECUTOR_PROMPT.format(
            task=state.task_description,
            pending_criteria=pending_text,
            iteration=state.iteration,
            max_iterations=state.max_iterations,
            progress_log=progress_text,
        )

        try:
            agent = AgentLoop(
                llm=self.llm,
                tools=self.tools,
                cwd=self.cwd,
                permission_mode=PermissionMode.YOLO,
                system_prompt=_EXECUTOR_SYSTEM,
            )
            agent.MAX_TURNS = 30
            agent.streaming = True
            agent.emitter = self.emitter
            result = agent.run(prompt)
            self.emitter.progress(f"[Ralph executor done ({len(result)} chars)]")
            return result
        except Exception as e:
            self.emitter.tool_result(f"[Ralph executor error: {e}]", is_error=True)
            return f"[Executor failed: {e}]"

    def _pending_criteria(self, state: RalphState) -> list[str]:
        """Return criteria that failed in the last verification, or all if none yet."""
        if not state.verification_results:
            return state.acceptance_criteria

        last = state.verification_results[-1]
        feedback = last.get("feedback", [])
        failed = [r["criterion"] for r in feedback if not r.get("passed", False)]
        return failed if failed else state.acceptance_criteria

    def _is_stalled(self, state: RalphState) -> bool:
        """Detect stall: same set of failing criteria for 3 consecutive iterations."""
        if len(state.verification_results) < 3:
            return False

        last_three = state.verification_results[-3:]

        def _failed_set(vr: dict) -> frozenset:
            return frozenset(
                r["criterion"]
                for r in vr.get("feedback", [])
                if not r.get("passed", False)
            )

        sets = [_failed_set(vr) for vr in last_three]
        # Stalled if all three have the same non-empty failure set
        return sets[0] == sets[1] == sets[2] and bool(sets[0])

    def _parse_verification_json(
        self, raw: str, criteria: list[str]
    ) -> list[dict]:
        """Parse JSON verification result from LLM response."""
        try:
            # Find JSON object in response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(raw[start:end])
                results = data.get("results", [])
                if results:
                    return results
        except Exception:
            pass

        # Fallback: mark all as failed
        return [
            {"criterion": c, "passed": False, "feedback": "Could not parse verification result."}
            for c in criteria
        ]

    def _generate_summary(self, state: RalphState) -> str:
        """Generate final summary of ralph execution."""
        lines = [
            f"[Ralph Complete] Status: {state.status}",
            f"Task: {state.task_description[:80]}",
            f"Iterations: {state.iteration}/{state.max_iterations}",
            "",
        ]

        if state.verification_results:
            last = state.verification_results[-1]
            feedback = last.get("feedback", [])
            passed = [r for r in feedback if r.get("passed")]
            failed = [r for r in feedback if not r.get("passed")]

            if passed:
                lines.append(f"Completed ({len(passed)}):")
                for r in passed:
                    lines.append(f"  + {r.get('criterion', '')[:70]}")

            if failed:
                lines.append(f"Incomplete ({len(failed)}):")
                for r in failed:
                    lines.append(f"  - {r.get('criterion', '')[:70]}")
                    if r.get("feedback"):
                        lines.append(f"    {r['feedback'][:80]}")

        return "\n".join(lines)
