"""Agent loop — prompt → LLM → tool → feedback cycle.

Python implementation of Claude Code's queryLoop() pattern (src/query.ts:241).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from typing import Callable

from .auto_agents import AutoAgentRunner
from .context import ContextManager, estimate_messages_tokens
from .events import AgentEventEmitter
from .hooks import HookEvent, HookRunner
from .llm_client import LLMClientBase, LLMResponse
from .memory import MemorySystem
from .permissions import PermissionChecker, PermissionMode
from .tools import Tool, ToolResult
from .version import VERSION
_logger = logging.getLogger(__name__)

from .loop_context import (
    _build_dynamic_context,
    _current_date,
    _find_project_config,
    _find_rules,
    _project_meta,
    _read_file_snippet,
    _read_task_state,
    _STATIC_SYSTEM_PROMPT,
    _task_state_path,
    _top_level_layout,
    _write_task_state,
)
from .loop_guards import LoopGuards
from .session_lifecycle import SessionLifecycle
from .tool_executor import ToolExecutor
from .context_injector import ContextInjector
from .stream_caller import StreamingCaller
from .loop_commands import (  # noqa: F401 — re-exported for hermit_agent.loop consumers
    SLASH_COMMANDS,
    TRIGGER_AGENT,
    TRIGGER_AGENT_SINGLE,
    _load_rules,
    _preprocess_slash_command,
    _resolve_skill_references,
    handle_slash_command,
)


class AgentLoop:
    """Core agent loop."""

    MAX_TURNS = 50

    def __init__(
        self,
        llm: LLMClientBase,
        tools: list[Tool],
        cwd: str = ".",
        permission_mode: PermissionMode = PermissionMode.ALLOW_READ,
        max_context_tokens: int = 32000,
        system_prompt: str | None = None,
        on_tool_result: "Callable[[str, str, bool], None] | None" = None,
        response_language: str = "English",
        seed_handoff: bool = True,
        auto_wrap: bool = True,
        session_id: str | None = None,
        session_kind: str | None = None,
    ):
        self.llm = llm
        self.emitter = AgentEventEmitter()
        self.tools = {t.name: t for t in tools}
        self._all_tools = self.tools.copy()

        # Register ToolSearchTool (reference to full tool list)
        from .tools import ToolSearchTool

        self.tools["tool_search"] = ToolSearchTool(self._all_tools)
        self._all_tools["tool_search"] = self.tools["tool_search"]

        # Track exit reason
        self.last_termination: str | None = None
        self.interrupted = False  # ESC interrupt flag (checked at loop top)
        # abort_event aborts blocking operations like LLM streaming or subprocesses.
        # When the bridge receives an interrupt message and sets it, the streaming
        # loop and BashTool's Popen polling wake up immediately. Cleared on every _run_loop entry.
        self.abort_event = threading.Event()
        self.cwd = os.path.abspath(cwd)
        self._guards = LoopGuards(self.cwd)
        self.emitter.set_log_file(os.path.join(self.cwd, ".hermit", "activity.log"))
        self.scratchpad_dir = os.path.join(os.path.expanduser("~"), ".hermit", "scratchpad")
        os.makedirs(self.scratchpad_dir, exist_ok=True)
        base_prompt = system_prompt if system_prompt is not None else _STATIC_SYSTEM_PROMPT
        self.response_language = response_language
        self.seed_handoff = seed_handoff
        self.auto_wrap = auto_wrap
        if response_language.strip().lower() in ("auto", "match", ""):
            lang_directive = "Respond in the same language the user used in their most recent message."
        else:
            lang_directive = f"Respond in {response_language}."
        self.system_prompt = f"{base_prompt}\n\n{lang_directive}"
        self.messages: list[dict] = []
        self.pinned_reminders: list[dict] = []  # G41: {"key": str, "content": str}
        self.turn_count = 0
        self._tool_call_count = 0  # cumulative tool call count in session (self-learning trigger)
        self.session_id = session_id if session_id is not None else uuid.uuid4().hex[:12]
        self._lifecycle = SessionLifecycle(llm=self.llm, session_id=self.session_id)
        self._executor = ToolExecutor(agent=self)
        self._injector = ContextInjector(agent=self)
        self.session_kind = session_kind
        self.streaming = True
        self.pending_user_messages: list[str] = []  # btw: queue of user messages received mid-run
        self._used_extended_tools = False  # whether extended tools were used (dynamic tool loading)
        self._dynamic_context = _build_dynamic_context(self.cwd)
        self._on_tool_result = on_tool_result  # progress streaming callback (optional)
        self._context_injected = False  # whether dynamic context was injected

        self.permission_checker = PermissionChecker(mode=permission_mode)
        self.token_totals: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        self._stream_caller = StreamingCaller(agent=self)

        self._state_file_edit_count = 0  # detect repeated task_state.md edit loops
        self._compact_count = 0
        self._loop_reentry_count = 0
        self._last_tool_sigs: list[tuple[str, str]] = []
        self._tool_repeat_count = 0
        self._ran_ralph = False

        # Inject emitter + permission_checker into SubAgentTool (after permission_checker is created)
        if "sub_agent" in self.tools:
            setattr(self.tools["sub_agent"], "_emitter", self.emitter)
            setattr(self.tools["sub_agent"], "_permission_checker", self.permission_checker)
        self.hook_runner = HookRunner()
        self.hook_runner.run_hooks(HookEvent.ON_START, "", {})

        # Plugin hook integration
        from .plugins import PluginRegistry

        self.plugin_registry = PluginRegistry()

        # Auto agents
        self.auto_agents = AutoAgentRunner()

        self.context_manager = ContextManager(
            max_context_tokens=max_context_tokens,
            llm=llm,
        )

        # Background agent tracking (fire-and-forget sub-agents)
        self._background_results: list[dict] = []  # {"description": str, "result": str}

        # Loop-detection state (also reset in run(), but initialize here for path-independence)
        self._last_text_sig: str = ""
        self._text_repeat_count: int = 0
        self._bg_lock = threading.Lock()

        # Wire background queue into SubAgentTool if present
        from .tools import SubAgentTool

        for tool in self.tools.values():
            if isinstance(tool, SubAgentTool):
                tool._bg_queue = (self._background_results, self._bg_lock)
                tool._bg_notify = self._on_bg_complete
                break

        # Inject abort_event so long-blocking tools like BashTool can detect it.
        # (Preserves existing execute signature by passing via instance attribute.)
        for tool in self._all_tools.values():
            try:
                tool._agent = self
            except Exception:
                pass  # best-effort: not all tool objects expose _agent attribute

    def reset_after_interrupt(self) -> None:
        """Remove messages from the in-flight turn from context on interrupt (§35c G36).

        Delete the last user message (the start of the interrupted turn) and
        every assistant/tool message after it. Earlier completed history is kept.

        This way the next /command after an interrupt starts in a clean context.
        """
        last_user_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx is not None:
            self.messages = self.messages[:last_user_idx]

    # Core tools: always included. The rest load after the first turn or for coding tasks.
    _CORE_TOOLS = {"bash", "read_file", "write_file", "edit_file", "glob", "grep"}

    def _tool_schemas(self) -> list[dict]:
        # First 2 turns: core tools only (saves tokens → faster response)
        # After that, or once tools have been used, include all tools
        if self.turn_count <= 2 and not self._used_extended_tools:
            schemas = [t.to_openai_schema() for t in self.tools.values() if t.name in self._CORE_TOOLS]
        else:
            schemas = [t.to_openai_schema() for t in self.tools.values()]
        return schemas

    def _restrict_tools(self, allowed_names: list[str] | None):
        """Temporarily restrict available tools. None = restore all."""
        if allowed_names is None:
            self.tools = self._all_tools.copy()
        else:
            self.tools = {k: v for k, v in self._all_tools.items() if k in allowed_names}

    def shutdown(self):
        """Exit handling after running OnExit hooks. Auto-saves handoff when HERMIT_AUTO_WRAP=1."""
        self.hook_runner.run_hooks(HookEvent.ON_EXIT, "", {})
        # OnStop: fire hook + agent-learner process for WRITE path
        try:
            self.hook_runner.run_hooks(HookEvent.ON_STOP, "", {
                "session_id": self.session_id,
                "model_id": getattr(self.llm, "model_id", ""),
                "tool_call_count": self._tool_call_count,
            })
        except Exception as exc:
            _logger.warning("ON_STOP hook failed: %s", exc)
        self._run_agent_learner_on_stop()
        try:
            from .session_wrap import maybe_auto_wrap

            maybe_auto_wrap(
                cwd=self.cwd,
                session_id=self.session_id,
                modified_files=list(self.auto_agents.modified_files),
                messages=self.messages,
            )
        except Exception as exc:
            _logger.warning("auto-wrap failed: %s", exc)
        # KB auto-extract — save domain knowledge to pending/ on session exit.
        # Low quality risk because it's not injected into wiki/.
        try:
            if self.auto_agents.modified_files:
                from .kb_learner import KBLearner

                kb = KBLearner(cwd=self.cwd, llm=self.llm)
                pytest_passed = bool(getattr(self, "_last_test_passed", False))
                facts = kb.extract_from_conversation(self.messages, pytest_passed=pytest_passed)
                for fact in (facts or []):
                    kb.save_pending(fact)
        except Exception as exc:
            _logger.warning("KB save_pending failed: %s", exc)

    def _run_agent_learner_on_stop(self) -> None:
        """Fire-and-forget agent-learner process on stop if installed.

        Uses start_new_session so the child survives parent SIGINT/SIGTERM.
        """
        if self.session_kind in ("gateway", "mcp"):
            return
        if not shutil.which("agent-learner"):
            return
        try:
            subprocess.Popen(
                [
                    "agent-learner", "process",
                    "--adapter", "hermit",
                    "--session-id", self.session_id or "",
                    "--cwd", self.cwd,
                    "--model-id", str(getattr(self.llm, "model_id", "")),
                    "--auto",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass  # best-effort: silently skip if spawn fails

    def _execute_tool(self, name: str, arguments: dict) -> ToolResult:
        return self._executor.execute_tool(name, arguments)

    def _abs_cwd_path(self, path: str) -> str:
        if not path:
            return ""
        return path if os.path.isabs(path) else os.path.abspath(os.path.join(self.cwd, path))

    def _edit_loop_guard(self, name: str, arguments: dict) -> ToolResult | None:
        """Delegates to LoopGuards.check_edit_loop(); adds guardrail attachment on block (G26/G48)."""
        result = self._guards.check_edit_loop(name, arguments)
        if result is not None:
            self._lifecycle.log_attachment("guardrail_trigger", "", gid="G26", reason="consecutive_edit_without_read")
        return result

    def _track_loop_state(self, name: str, arguments: dict, result: ToolResult) -> None:
        """Track tool call history — delegates edit/read/test state to LoopGuards; keeps skill logging."""
        self._guards.track(name, arguments, result)

        if name == "run_skill":
            skill_name = arguments.get("name", "")
            self._lifecycle.log_attachment("guardrail_trigger", "", gid="G29A", reason=f"skill_lazy_load:{skill_name}")
            if "deep-interview" in skill_name or "deep_interview" in skill_name:
                self._lifecycle.log_attachment("guardrail_trigger", "", gid="G34", reason="deep_interview_skip_routing")
            return

        if name in ("edit_file", "write_file") and not result.is_error:
            p = arguments.get("path", "")
            if p and "task_state" in os.path.basename(p):
                self._state_file_edit_count += 1

    def _maybe_inject_test_failure_hint(self) -> None:
        """If run_tests has failed 2+ consecutive times, inject a system-reminder before the next LLM call.

        Does not re-inject for the same failure count.
        """
        if self._guards.consecutive_test_failures < 2:
            return
        if self._guards._last_test_hint_count == self._guards.consecutive_test_failures:
            return
        self.messages.append(
            {
                "role": "user",
                "content": (
                    "<system-reminder>\n"
                    f"run_tests has failed {self._guards.consecutive_test_failures} consecutive times. "
                    "Do not repeatedly edit the same file on guesses. Do these steps first:\n"
                    "1. Re-read the failing test file and the target file with read_file.\n"
                    "2. Search relevant functions/classes/error messages with grep.\n"
                    "3. Only call edit_file after identifying the root cause.\n"
                    "</system-reminder>"
                ),
            }
        )
        self._guards._last_test_hint_count = self._guards.consecutive_test_failures

    def _on_bg_complete(self, description: str):
        """Callback for background-agent completion notifications (overridable in bridge.py)."""

    def _pin_pr_body(self, user_message: str) -> None:
        """G41: on `/feature-develop <PR_NUM>` input, save the PR body to pinned_reminders.

        Used for re-injection after compaction. Silently ignores gh command failures.
        """
        import re

        m = re.search(r"/feature-develop\s+(\d+)", user_message)
        if not m:
            return
        pr_num = m.group(1)
        key = f"pr_{pr_num}"
        try:
            result = subprocess.run(
                ["gh", "pr", "view", pr_num, "--json", "body,title"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return
            title = data.get("title", "")
            body = data.get("body", "")
            content = f"=== PR #{pr_num} original description ===\nTitle: {title}\n\n{body}"
            # Overwrite if same key, otherwise append
            for i, pin in enumerate(self.pinned_reminders):
                if pin["key"] == key:
                    self.pinned_reminders[i] = {"key": key, "content": content}
                    return
            self.pinned_reminders.append({"key": key, "content": content})
        except Exception as exc:
            _logger.warning("PR description fetch failed: %s", exc)

    _USER_CORRECTION_PATTERNS = [
        "no that's not", "that's not it", "why again", "how many times", "keeps doing the same", "again?",
        "do it again", "that's weird", "wrong", "something's off",
    ]

    def _detect_user_correction(self, message: str) -> None:
        """On detecting a user-correction pattern, record a user_correction attachment."""
        for pattern in self._USER_CORRECTION_PATTERNS:
            if pattern in message:
                self._lifecycle.log_attachment(
                    "user_correction", message[:200],
                    pattern=pattern,
                )
                break

    def _log_session_outcome(self) -> None:
        self._lifecycle.log_session_outcome(
            model=getattr(self.llm, "model", "unknown"),
            last_termination=self.last_termination,
            compact_count=self._compact_count,
            test_pass_count=self._guards.total_test_passes,
            test_fail_count=self._guards.total_test_failures,
            loop_reentry_count=self._loop_reentry_count,
        )

    def _archive_session(self) -> None:
        self._lifecycle.archive_session()

    def run(self, user_message: str) -> str:
        """Run the agent loop. Streams output in real time if streaming is enabled."""
        # G38b: Reset text loop detection state on run() entry
        self._last_text_sig = ""
        self._text_repeat_count = 0
        # Reset tool repeat detection on each user turn (prevents cross-turn false positives)
        self._last_tool_sigs = []
        self._tool_repeat_count = 0
        # G41: Save PR body to pinned_reminders (for re-injection after compact)
        self._pin_pr_body(user_message)
        # Slash command -> skill execution enables auto-continue
        raw_msg = user_message.lstrip()
        if raw_msg.startswith("/"):
            self._skill_active = True
            self._auto_continue_count = 0
        # User correction pattern detection (Phase 2 signal collection)
        self._detect_user_correction(user_message)

        # -- First turn: LLM classification (minimal prompt, no tools, no context) --
        if not self._context_injected and not self.messages and getattr(self, "session_kind", None) != "interactive":
            classify_response = self._classify_with_minimal_call(user_message)
            if classify_response is not None:
                # Simple question -> return classification response as-is.
                # Emit it via the streaming channel when streaming is on,
                # so `hermit "..."` shows the answer. main() skips
                # print(result) when streaming=True.
                if getattr(self, "streaming", False):
                    self.emitter.text(classify_response)
                self._log_session_outcome()
                return classify_response
            # NEED_TOOLS -> proceed with full context + tools

        # Seed injection — only on coding path (NEED_TOOLS), first turn, best-effort
        if not self._context_injected:
            user_message = self._injector.inject_seed_handoff(user_message)

        # Inject dynamic context on first turn (git status, etc. -- does not affect KV cache)
        if not self._context_injected and self._dynamic_context:
            user_message = f"<context>\n{self._dynamic_context}\n</context>\n\n{user_message}"
            self._context_injected = True
        self.messages.append({"role": "user", "content": user_message})
        result = self._run_loop()
        self._log_session_outcome()
        self._archive_session()
        return result

    def _classify_with_minimal_call(self, user_message: str) -> str | None:
        return self._injector.classify(user_message)

    def _run_loop(self, single_turn: bool = False) -> str:
        """Internal agent loop. Runs the loop without adding messages.

        single_turn: If True, returns immediately after one text response (no tool calls).
        """
        # Start new execution -- clear previous abort signal.
        self.abort_event.clear()

        while True:
            self.turn_count += 1

            if self.interrupted:
                self.last_termination = "interrupted"
                self.interrupted = False
                self.abort_event.clear()
                # G36: Remove interrupted turn messages from context so the next
                # /command starts in a clean state.
                self.reset_after_interrupt()
                return "[Agent interrupted]"

            # Inject user messages accumulated between tool calls into the next LLM turn.
            # Claude Code pattern: check pending input right after tool call.
            if self.pending_user_messages:
                for user_msg in self.pending_user_messages:
                    self.messages.append(
                        {
                            "role": "user",
                            "content": f"[User message during execution]\n{user_msg}",
                        }
                    )
                self.pending_user_messages.clear()

            if self.turn_count > self.MAX_TURNS:
                self.last_termination = "max_turns"
                return f"[Agent stopped: max turns ({self.MAX_TURNS}) reached]"

            # Inject completed background agent results into context
            with self._bg_lock:
                if self._background_results:
                    for bg in self._background_results:
                        self.messages.append(
                            {
                                "role": "user",
                                "content": f"[Background agent completed: {bg['description']}]\n{bg['result']}",
                            }
                        )
                    self._background_results.clear()

            # Context compression check
            compact_level = self.context_manager.get_compact_level(self.messages)
            if compact_level > 0:
                self._compact_count += 1
                token_count = estimate_messages_tokens(self.messages)
                trigger_point = int(self.context_manager.threshold * self.context_manager.compact_start_ratio)
                self.emitter.compact_notice(token_count, self.context_manager.threshold, compact_level, trigger_point=trigger_point)

                # Hook: save fallback handoff BEFORE compact mutates messages (L2+)
                _seed_enabled = os.environ.get("HERMIT_SEED_HANDOFF", "1").lower() not in ("0", "false", "no", "off")
                if _seed_enabled and getattr(self, "seed_handoff", True) and compact_level >= 2:
                    try:
                        from .session_wrap import save_pre_compact_snapshot
                        save_pre_compact_snapshot(self.messages, self.session_id, cwd=self.cwd)
                    except Exception as _e:
                        if hasattr(self.emitter, "log_exception"):
                            self.emitter.log_exception(_e)

                self.messages = self.context_manager.compact(self.messages)

                # Hook: on Level 4, save rich handoff if LLM summary succeeded
                if _seed_enabled and getattr(self, "seed_handoff", True) and compact_level == 4:
                    try:
                        first = self.messages[0] if self.messages else {}
                        first_content = first.get("content", "")
                        if isinstance(first_content, str) and first_content.startswith("[Conversation summary]"):
                            from .session_wrap import build_handoff_rich, save_handoff
                            rich = build_handoff_rich(self.messages, self.session_id)
                            save_handoff(rich, session_id=self.session_id, cwd=self.cwd, prefix="auto-compact-")
                    except Exception:
                        pass  # Handoff is best-effort; compact still succeeded
                # Re-inject project config after compression -- Claude Code's system-reminder pattern.
                # Prevents HERMIT.md rules injected during skill execution from being lost to compression.
                reminder_parts: list[str] = []
                project_config = _find_project_config(self.cwd)
                if project_config:
                    reminder_parts.append(project_config)
                project_rules = _find_rules(self.cwd)
                if project_rules:
                    reminder_parts.append(project_rules)
                # SDD task state re-injection -- restore progress lost to compact
                task_state = _read_task_state(self.cwd)
                if task_state:
                    reminder_parts.append(f"## Current Task State\n{task_state}")
                # G41: PR body re-injection -- restore PR description lost to compact
                for pin in self.pinned_reminders:
                    reminder_parts.append(pin["content"])
                if reminder_parts:
                    self.messages.append(
                        {
                            "role": "user",
                            "content": f"<system-reminder>\n{'---'.join(reminder_parts)}\n</system-reminder>",
                        }
                    )

            # S29 Bug 1 (G26): Force read_file hint injection on consecutive test failures
            self._maybe_inject_test_failure_hint()

            response = self._call_streaming()

            if response is None:
                self.last_termination = "error"
                return "[LLM error]"

            # No tool calls -> final response
            if not response.has_tool_calls:
                # Race gate: interrupt may have arrived right after chat_stream completed.
                # If the LLM responded quickly (< 3s) and the user pressed ESC immediately after,
                # the watcher thread's abort check fires after the stream ended. Block here
                # to prevent displaying the LLM response as an assistant message.
                if self.abort_event.is_set() or self.interrupted:
                    self.last_termination = "interrupted"
                    self.interrupted = False
                    self.abort_event.clear()
                    # G36: Clean up interrupted turn messages
                    self.reset_after_interrupt()
                    return "[Agent interrupted]"

                # single_turn mode: return text response immediately (interview and other interactive modes)
                if single_turn:
                    if response.content:
                        self.messages.append({"role": "assistant", "content": response.content})
                        self._lifecycle.log_assistant_text(response.content)
                    return response.content or "[No response]"

                if response.content:
                    self.messages.append({"role": "assistant", "content": response.content})
                    self._lifecycle.log_assistant_text(response.content)

                # Auto-continue: auto-resume when a skill stops with a text-only response
                # SDD pattern -- only works when _skill_active flag is set
                # (only set during skill execution to prevent triggering on regular user messages)
                # In _skill_active mode, auto-continue is unlimited until the skill finishes
                # However, if consecutive text-only responses exceed MAX_TEXT_ONLY_STREAK, treat as stuck and stop
                MAX_AUTO_CONTINUE = 999 if getattr(self, "_skill_active", False) else 5
                MAX_TEXT_ONLY_STREAK = 5  # Max consecutive responses without tool calls (reset on tool call)
                _auto_count = getattr(self, "_auto_continue_count", 0)
                _text_only_streak = getattr(self, "_consecutive_text_only_count", 0)
                if _auto_count < MAX_AUTO_CONTINUE and getattr(self, "_skill_active", False):
                    if _text_only_streak >= MAX_TEXT_ONLY_STREAK:
                        # Exceeded consecutive text-only MAX_TEXT_ONLY_STREAK -> treat as stuck, force skill stop
                        self._consecutive_text_only_count = 0
                        self._auto_continue_count = 0
                        self._skill_active = False
                        self._restrict_tools(None)
                        self.emitter.progress(
                            f"[Auto-continue] {_text_only_streak} consecutive responses without tool calls -> stopping"
                        )
                        return response.content or "[Task completed]"
                    self._consecutive_text_only_count = _text_only_streak + 1
                    self._auto_continue_count = _auto_count + 1
                    self._loop_reentry_count += 1
                    task_state = _read_task_state(self.cwd)
                    has_unchecked = "- [ ]" in task_state or "* [ ]" in task_state
                    state_hint = (
                        "task_state.md has unchecked items that are not yet complete. "
                        "Mark completed items with `- [x]`."
                        if has_unchecked
                        else "Record current progress in task_state.md and continue."
                    )
                    if _text_only_streak >= 3:
                        # 3+ consecutive text-only -> strong prompt to force tool call
                        prompt_content = (
                            f"You have output text-only responses {_text_only_streak + 1} times in a row. "
                            "You MUST call a tool now. "
                            "Immediately call an appropriate tool (bash_tool, edit_file, run_tests, etc.). "
                            "Outputting text alone will not complete the task."
                        )
                    else:
                        prompt_content = f"The task is not yet complete. {state_hint} Execute the next step."
                    self.emitter.progress(
                        f"[Auto-continue {self._auto_continue_count}/{MAX_AUTO_CONTINUE}] continuing..."
                    )
                    self.messages.append({"role": "user", "content": prompt_content})
                    continue  # Restart loop

                # G38: On empty response, request summary once (prevent silently ending the turn)
                if not response.content and not getattr(self, "_summary_retry_done", False):
                    self._summary_retry_done = True
                    self._lifecycle.log_attachment("guardrail_trigger", "", gid="G38", reason="empty_response_summary_enforce")
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "<system-reminder>\n"
                                "The previous turn tried to end without text. The user cannot tell what was done. "
                                "Now output a 2-3 sentence summary: "
                                "(1) what was just done, (2) current status (success/failure/pending), "
                                "(3) what the user can do next. "
                                "If additional tool calls are actually needed, you may perform those as well.\n"
                                "</system-reminder>"
                            ),
                        }
                    )
                    continue  # Restart loop, expect summary in second response

                self._summary_retry_done = False  # Turn ended successfully, reset for next turn
                self._auto_continue_count = 0  # Reset
                self._skill_active = False  # Skill ended
                self.last_termination = "completed" if response.content else "empty_response"
                self._restrict_tools(None)  # Restore skill tool restrictions
                return response.content or "[No response]"

            # Loop detection: force stop on 3+ consecutive identical tool+args repeats
            # Polling tools (monitor, check_task) are exempt — repeated identical calls are intentional
            _POLLING_TOOLS = {"monitor", "mcp__hermit-channel__check_task"}
            if response.tool_calls:
                call_sig = [(tc.name, json.dumps(tc.arguments, sort_keys=True)) for tc in response.tool_calls]
                is_polling = all(tc.name in _POLLING_TOOLS for tc in response.tool_calls)
                if not is_polling:
                    if self._last_tool_sigs and self._last_tool_sigs == call_sig:
                        self._tool_repeat_count += 1
                    else:
                        self._tool_repeat_count = 0
                    self._last_tool_sigs = call_sig
                if not is_polling and self._tool_repeat_count >= 4:
                    self.messages.append({"role": "assistant", "content": "Stopping: identical tool call repeated."})
                    self.last_termination = "tool_loop"
                    return "Stopping: identical tool call repeated. Please try a different approach."

            # task_state.md repeated edit loop detection (args vary each time, so _tool_repeat_count doesn't catch it)
            if self._state_file_edit_count >= 15:
                self.messages.append({"role": "assistant", "content": "Stopping: task_state.md repeated edit loop detected."})
                self.last_termination = "state_file_loop"
                self._lifecycle.log_attachment("guardrail_trigger", "", gid="G50", reason="state_file_edit_loop")
                return "Stopping: detected a loop of repeated task_state.md edits. Treating the task as completed."

            # Loop detection G38b: force stop on 5+ consecutive identical text content + identical tool calls
            # (if tool calls change, treat as progress and reset counter)
            if response.tool_calls and response.content:
                text_sig = response.content.strip()
                cur_call_sig = [(tc.name, json.dumps(tc.arguments, sort_keys=True)) for tc in response.tool_calls]
                if text_sig and text_sig == self._last_text_sig and cur_call_sig == getattr(self, "_last_tool_sigs", None):
                    self._text_repeat_count += 1
                else:
                    self._text_repeat_count = 0
                    self._last_text_sig = text_sig
                if self._text_repeat_count >= 5:
                    self.messages.append({"role": "assistant", "content": "Stopping: identical text response repeated."})
                    self.last_termination = "text_loop"
                    self._lifecycle.log_attachment("guardrail_trigger", "", gid="G38b", reason="text_loop_detected")
                    return "Stopping: identical text response repeated."

            # Add assistant message
            assistant_msg: dict = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else tc.arguments,
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            self.messages.append(assistant_msg)
            if response.content:
                self._lifecycle.log_assistant_text(response.content)

            # Tool execution + result feedback (parallel optimization)
            self._consecutive_text_only_count = 0  # Tool call occurred -> reset text-only streak
            paused = self._execute_tool_calls(response.tool_calls)
            if paused:
                # ask_user_question called -- waiting for user response.
                # Keep _skill_active True -- user response should continue the interview.
                # Reset auto-continue count -- start fresh 5-count in the new turn.
                # (Claude Code's AskUserQuestion interruption pattern)
                self._auto_continue_count = 0
                self.last_termination = "waiting_for_user"
                return ""

    def _reset_tool_call_count(self) -> None:
        self._tool_call_count = 0

    def _execute_tool_calls(self, tool_calls) -> bool:
        return self._executor.execute_tool_calls(tool_calls)

    def _partition_tool_calls(self, tool_calls) -> list[tuple[list, bool]]:
        return self._executor.partition_tool_calls(tool_calls)

    def _call_streaming(self) -> LLMResponse | None:
        return self._stream_caller.call()

