"""Learner — automatic skill creation, validation, performance tracking, and auto-deprecation.

Pipeline:
  execution complete → pytest auto-run → pattern extraction → save as pending
           → promoted to approved on pytest pass
           → success/fail counter updated on each use
           → success_rate < threshold → auto-moved to deprecated
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .learner_extraction import build_failure_prompt, build_success_prompt, extract_skill_data
from .learner_reporting import build_status_report, collect_active_skills
from .learner_verification import evaluate_cleanup_action, resolve_verify_cmd, run_pytest_check, run_verify_command
from .learner_storage import SkillMeta
from .learner_storage import add_hub_backlink as _add_hub_backlink
from .learner_storage import current_day as _now
from .learner_storage import load_verify_rules as _load_verify_rules
from .learner_storage import parse_skill_file as _parse_skill_file
from .learner_storage import write_skill_file as _write_skill_file


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Deprecated: use Learner(root=cwd).learned_feedback_dir etc.
LEARNED_FEEDBACK_DIR = ".hermit/skills/learned-feedback"
PENDING_DIR = ".hermit/skills/learned-feedback/pending"
APPROVED_DIR = ".hermit/skills/learned-feedback/approved"
DEPRECATED_DIR = ".hermit/skills/learned-feedback/deprecated"
AUTO_LEARNED_DIR = ".hermit/skills/auto-learned"

_DEFAULT_LEARNED_FEEDBACK_DIR = LEARNED_FEEDBACK_DIR
_DEFAULT_PENDING_DIR = PENDING_DIR
_DEFAULT_APPROVED_DIR = APPROVED_DIR
_DEFAULT_DEPRECATED_DIR = DEPRECATED_DIR
_DEFAULT_AUTO_LEARNED_DIR = AUTO_LEARNED_DIR

# Deprecation criteria
MIN_USES_BEFORE_EVAL = 5   # evaluate success_rate only after N or more uses
DEPRECATE_THRESHOLD = 0.4  # auto-deprecate if success_rate falls below this
UNUSED_DAYS_THRESHOLD = 30 # archive if unused for this many days


# ---------------------------------------------------------------------------
# Metadata / file helper compatibility re-exports
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class Learner:
    """Skill lifecycle manager.

    pending  → (pytest passes) → approved → (tracked during use) → deprecated
    """

    def __init__(self, llm=None, root: str | None = None):
        self.llm = llm
        self.root = root or os.getcwd()

        use_legacy_overrides = root is None and (
            PENDING_DIR != _DEFAULT_PENDING_DIR
            or APPROVED_DIR != _DEFAULT_APPROVED_DIR
            or DEPRECATED_DIR != _DEFAULT_DEPRECATED_DIR
            or AUTO_LEARNED_DIR != _DEFAULT_AUTO_LEARNED_DIR
        )

        if use_legacy_overrides:
            self.pending_dir = PENDING_DIR
            self.approved_dir = APPROVED_DIR
            self.deprecated_dir = DEPRECATED_DIR
            self.auto_learned_dir = AUTO_LEARNED_DIR
            self.learned_feedback_dir = LEARNED_FEEDBACK_DIR
        else:
            self.learned_feedback_dir = os.path.join(self.root, ".hermit", "skills", "learned-feedback")
            self.pending_dir = os.path.join(self.learned_feedback_dir, "pending")
            self.approved_dir = os.path.join(self.learned_feedback_dir, "approved")
            self.deprecated_dir = os.path.join(self.learned_feedback_dir, "deprecated")
            self.auto_learned_dir = os.path.join(self.root, ".hermit", "skills", "auto-learned")
        for d in (self.pending_dir, self.approved_dir, self.deprecated_dir, self.auto_learned_dir):
            os.makedirs(d, exist_ok=True)

    def _skill_path(self, status: str, name: str) -> str:
        dirs = {"pending": self.pending_dir, "approved": self.approved_dir, "deprecated": self.deprecated_dir}
        return os.path.join(dirs.get(status, self.approved_dir), f"{name}.md")

    @staticmethod
    def should_run(session_kind: str | None) -> bool:
        """Return False for gateway/MCP sessions."""
        return session_kind not in ('gateway', 'mcp')

    # ------------------------------------------------------------------
    # Skill extraction (LLM-based)
    # ------------------------------------------------------------------

    def extract_from_failure(self, messages: list[dict], pytest_output: str) -> dict | None:
        """Extract an improvement rule from pytest failure output and conversation history."""
        if not self.llm:
            return None

        prompt = build_failure_prompt(pytest_output)
        return extract_skill_data(self.llm, prompt)

    def extract_from_success(self, messages: list[dict], tool_call_count: int) -> dict | None:
        """Extract a reusable pattern from a successful task with 5+ tool calls."""
        if tool_call_count < 5:
            return None
        if not self.llm:
            return None

        # summarise only assistant/tool content from recent conversation (token saving)
        relevant = [
            m for m in messages[-30:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        conversation_summary = "\n".join(
            f"[{m['role']}] {str(m['content'])[:300]}" for m in relevant
        )

        prompt = build_success_prompt(conversation_summary, tool_call_count)
        return extract_skill_data(self.llm, prompt)

    def save_auto_learned(self, skill_data: dict) -> str | None:
        """Save a self-learned skill directly to auto-learned/ (no pending stage, auto-approved)."""
        name = skill_data.get("name", "")
        if not name:
            return None

        triggers = json.dumps(skill_data.get("triggers", []))
        scope = json.dumps(skill_data.get("scope", []))
        # verify_cmd: fall back to rules table if not present in extracted data
        verify_cmd = skill_data.get("verify_cmd", "")
        if not verify_cmd:
            rules = _load_verify_rules()
            verify_cmd = rules.get("by_name", {}).get(name, "")

        frontmatter = (
            f"name: {name}\n"
            f"description: {skill_data.get('description', '')}\n"
            f"type: auto-learned\n"
            f"status: auto-learned\n"
            f"triggers: {triggers}\n"
            f"scope: {scope}\n"
            f"created_at: {_now()}\n"
            f"last_used: \n"
            f"use_count: 0\n"
            f"success_count: 0\n"
            f"fail_count: 0\n"
            f"success_rate: 0.00\n"
            f"missed_count: 0\n"
            f"needs_review: false\n"
            f"verify_cmd: {verify_cmd}\n"
        )
        body = f"""## Rule

{skill_data.get('rule', '')}

**Why**: {skill_data.get('why', '')}

## Good Pattern

```
{skill_data.get('good_pattern', '')}
```

## Anti-Pattern

```
{skill_data.get('bad_pattern', '')}
```
"""
        content = f"---\n{frontmatter}---\n\n{body}\n"

        # Security scan
        from .learner_guard import scan_skill_content
        safe, reason = scan_skill_content(content)
        if not safe:
            print(f"\033[31m  [Learner] skill blocked ({name}): {reason}\033[0m")
            return None

        path = os.path.join(self.auto_learned_dir, f"{name}.md")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content)
        _add_hub_backlink(path, "_hub_auto")
        return path

    # ------------------------------------------------------------------
    # Save as pending
    # ------------------------------------------------------------------

    def save_pending(self, skill_data: dict) -> str | None:
        """Save an extracted skill as pending."""
        name = skill_data.get("name", "")
        if not name:
            return None

        # skip if already in approved
        if os.path.exists(self._skill_path("approved", name)):
            return None

        meta = SkillMeta(
            name=name,
            description=skill_data.get("description", ""),
            triggers=skill_data.get("triggers", []),
            scope=skill_data.get("scope", []),
            status="pending",
            created_at=_now(),
        )

        body = f"""## Rule

{skill_data.get('rule', '')}

**Why**: {skill_data.get('why', '')}

## Good Pattern

```
{skill_data.get('good_pattern', '')}
```

## Anti-Pattern

```
{skill_data.get('bad_pattern', '')}
```
"""
        path = self._skill_path("pending", name)
        _write_skill_file(path, meta, body)
        return path

    # ------------------------------------------------------------------
    # Run pytest + auto-promote
    # ------------------------------------------------------------------

    def run_pytest_and_promote(self, cwd: str, skill_name: str) -> tuple[bool, str]:
        """Run pytest and promote pending → approved on pass.

        Returns: (passed, pytest_output)
        """
        passed, output = run_pytest_check(cwd)

        if passed:
            self._promote(skill_name)

        return passed, output

    def _promote(self, name: str) -> None:
        """Move pending → approved."""
        src = self._skill_path("pending", name)
        dst = self._skill_path("approved", name)
        if not os.path.exists(src):
            return
        parsed = _parse_skill_file(src)
        if not parsed:
            return
        meta, body = parsed
        meta.status = "approved"
        _write_skill_file(dst, meta, body)
        os.remove(src)
        _add_hub_backlink(dst, "_hub_approved")

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def record_run(
        self,
        skill_names: list[str],
        pytest_passed: bool | None = None,
        verify_results: dict[str, bool | None] | None = None,
    ) -> None:
        """Update success/fail counters for each skill after execution.

        pytest_passed: primary success signal (no exception=True, exception=False, not run=None)
        verify_results: {skill_name: bool | None} — verify_cmd execution results.
          True  = verification passed (success confirmed)
          False = verification failed (includes false positives — always recorded as failure)
          None  = verify_cmd not defined or not runnable (fall back to pytest_passed signal)

        verify_results takes precedence over pytest_passed when provided.
        """
        verify_results = verify_results or {}

        for name in skill_names:
            path = self._skill_path("approved", name)
            if not os.path.exists(path):
                path = os.path.join(self.auto_learned_dir, f"{name}.md")
            if not os.path.exists(path):
                continue
            parsed = _parse_skill_file(path)
            if not parsed:
                continue
            meta, body = parsed
            meta.use_count += 1
            meta.last_used = _now()

            # determine final success/failure: verify_result takes priority, fallback → pytest_passed
            verified = verify_results.get(name)  # True / False / None
            if verified is True:
                meta.success_count += 1
            elif verified is False:
                # verification failed — includes LLM false positives
                meta.fail_count += 1
            elif pytest_passed is True:
                meta.success_count += 1
            elif pytest_passed is False:
                meta.fail_count += 1
            # verified=None AND pytest_passed=None → only use_count/last_used updated

            _write_skill_file(path, meta, body)

        # cleanup after counter update
        self.cleanup()

    def record_missed(self, skill_names: list[str]) -> None:
        """Increment missed_count when a skill was matched but the LLM did not actually follow it.

        Called after task completion for skills that were injected but not reflected in the result.
        """
        for name in skill_names:
            path = self._skill_path("approved", name)
            if not os.path.exists(path):
                path = os.path.join(self.auto_learned_dir, f"{name}.md")
            if not os.path.exists(path):
                continue
            parsed = _parse_skill_file(path)
            if not parsed:
                continue
            meta, body = parsed
            meta.missed_count += 1
            _write_skill_file(path, meta, body)

    # ------------------------------------------------------------------
    # Auto-deprecation
    # ------------------------------------------------------------------

    def cleanup(self) -> list[str]:
        """Manage underperforming skills. Targets both approved and auto-learned.

        Two-stage policy:
          Stage 1 (needs_review): success rate drops → set needs_review=True flag → prompt improvement
          Stage 2 (deprecated): continued failures while in needs_review state → auto-deprecate
        """
        deprecated = []
        targets = list(Path(self.approved_dir).glob("*.md")) + list(Path(self.auto_learned_dir).glob("*.md"))
        for p in targets:
            parsed = _parse_skill_file(str(p))
            if not parsed:
                continue
            meta, body = parsed

            action, reason = evaluate_cleanup_action(
                meta,
                min_uses_before_eval=MIN_USES_BEFORE_EVAL,
                deprecate_threshold=DEPRECATE_THRESHOLD,
                unused_days_threshold=UNUSED_DAYS_THRESHOLD,
            )

            if action == "deprecate":
                meta.status = "deprecated"
                dst = self._skill_path("deprecated", meta.name)
                _write_skill_file(dst, meta, body + f"\n\n<!-- deprecated: {reason} -->")
                os.remove(str(p))
                deprecated.append(meta.name)
                print(f"\033[33m  [Learner] skill deprecated: {meta.name} ({reason})\033[0m")
            elif action == "review" and not meta.needs_review:
                meta.needs_review = True
                _write_skill_file(str(p), meta, body)
                print(f"\033[33m  [Learner] skill needs review: {meta.name} ({reason})\033[0m")

        return deprecated

    # ------------------------------------------------------------------
    # Run verify_cmd (validate result after task completion)
    # ------------------------------------------------------------------

    def run_verify_cmds(self, skill_names: list[str], cwd: str) -> dict[str, bool | None]:
        """Run each skill's verify_cmd to validate actual success.

        verify_cmd resolution priority:
          1. verify_cmd in the skill file frontmatter (directly defined)
          2. ~/.hermit/skills/verify-rules.json by_name table (name match)
          3. verify-rules.json by_trigger_keyword table (trigger keyword match)
          4. None if not found (no signal)

        Returns: {skill_name: True/False/None}
          True  = verify_cmd exit 0 (success confirmed)
          False = verify_cmd non-zero (failure — includes LLM false positives)
          None  = verify_cmd not defined (no signal)
        """
        import subprocess

        rules = _load_verify_rules()
        results: dict[str, bool | None] = {}

        for name in skill_names:
            path = self._skill_path("approved", name)
            if not os.path.exists(path):
                path = os.path.join(self.auto_learned_dir, f"{name}.md")

            meta = None
            if os.path.exists(path):
                parsed = _parse_skill_file(path)
                if parsed:
                    meta, _ = parsed

            cmd = resolve_verify_cmd(name, meta, rules)
            results[name] = run_verify_command(cmd, cwd)

        return results

    # ------------------------------------------------------------------
    # Load active skills (for injection)
    # ------------------------------------------------------------------

    def get_active_skills(self, context_keywords: list[str] | None = None) -> list[tuple[str, str]]:
        """Return approved + auto-learned skills that match the current context.

        Returns: [(name, body), ...]
        """
        return collect_active_skills(
            approved_dir=self.approved_dir,
            auto_learned_dir=self.auto_learned_dir,
            parse_skill_file=_parse_skill_file,
            context_keywords=context_keywords,
        )

    # ------------------------------------------------------------------
    # Status report
    # ------------------------------------------------------------------

    def status_report(self) -> str:
        return build_status_report(
            pending_dir=self.pending_dir,
            approved_dir=self.approved_dir,
            deprecated_dir=self.deprecated_dir,
            auto_learned_dir=self.auto_learned_dir,
            parse_skill_file=_parse_skill_file,
        )


def learner_enabled_for(session_kind: str | None) -> bool:
    """Module-level helper — returns False for gateway/MCP sessions."""
    return Learner.should_run(session_kind)
