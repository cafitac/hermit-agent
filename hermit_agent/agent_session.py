"""AgentSession — AgentLoop execution lifecycle defined with Template Method Pattern.

Common flow: setup → prepare_prompt → execute → teardown
  - SessionLogger, Learner, skill injection, and post-run stats are shared across all modes.
  - Tool initialization, agent execution strategy, and error/completion notifications are implemented by subclasses.

Implementations (2 types):
  MCPAgentSession    — MCP server mode (background thread, channel notify, cancel event)
  CLIAgentSession    — Direct terminal execution mode (synchronous, streaming)
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

from .session_logging import attach_session_logger
from .session_support import infer_context_size as _infer_context_size

if TYPE_CHECKING:
    from .llm_client import LLMClientBase
    from .loop import AgentLoop
    from .permissions import PermissionMode


class AgentSessionBase(ABC):
    """Template Method: Skeleton for AgentLoop execution lifecycle.

    Abstract methods that subclasses must implement:
      _setup_tools()   — Tool initialization (differs per MCP/Bridge/CLI channel)
      _execute()       — Agent execution strategy

    Hook methods that subclasses may override:
      _setup_permission_checker() — Replace the permission checker
      _make_progress_hook()       — Return a progress hook
      _on_success()               — Notification/post-processing on success
      _on_error()                 — Notification/post-processing on error
    """

    _session_mode = "single"
    _session_kind: str | None = None

    def __init__(
        self,
        llm: "LLMClientBase",
        cwd: str,
        permission_mode: "PermissionMode",
        max_turns: int = 200,
        max_context_tokens: int = 32000,
    ):
        self.llm = llm
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.max_turns = max_turns
        self.max_context_tokens = max_context_tokens

        self._agent: "AgentLoop | None" = None
        self._active_skill_names: list[str] = []

    # ------------------------------------------------------------------
    # Template method — external entry point
    # ------------------------------------------------------------------

    def run(self, task: str) -> str:
        """Execute a task and return the result string."""
        self._setup_agent()
        self._setup_session_logger()
        prompt = self._prepare_prompt(task)

        result: str | None = None
        succeeded: bool | None = None
        try:
            result = self._execute(prompt)
            succeeded = True
            self._on_success(result)
            return result or ""
        except Exception as e:
            succeeded = False
            self._on_error(e)
            raise
        finally:
            self._schedule_teardown(succeeded)

    # ------------------------------------------------------------------
    # Common implementation — behaves identically across all subclasses
    # ------------------------------------------------------------------

    def _setup_agent(self) -> None:
        """Common AgentLoop initialization."""
        from .config import load_settings
        from .loop import AgentLoop
        tools = self._setup_tools()
        _cfg = load_settings(cwd=self.cwd)
        self._agent = AgentLoop(
            llm=self.llm,
            tools=tools,
            cwd=self.cwd,
            permission_mode=self.permission_mode,
            max_context_tokens=self.max_context_tokens,
            on_tool_result=self._make_progress_hook(),
            seed_handoff=_cfg.get("seed_handoff", True),
            auto_wrap=_cfg.get("auto_wrap", True),
            session_kind=getattr(self, '_session_kind', None),
        )
        self._agent.MAX_TURNS = self.max_turns
        self._setup_permission_checker()

    def _setup_session_logger(self) -> None:
        """Inject SessionLogger into LLM + emitter."""
        if self._agent is None:
            return
        try:
            attach_session_logger(
                llm=self.llm,
                agent=self._agent,
                mode=self._session_mode,
                cwd=self.cwd,
                parent_session_id=getattr(self, 'parent_session_id', None),
                session_id=self._agent.session_id,
            )
        except Exception:
            pass

    def _prepare_prompt(self, task: str) -> str:
        """Inject learned-feedback skills before the task prompt."""
        try:
            from .learner import Learner
            learner = Learner(llm=self.llm)
            active_skills = learner.get_active_skills()
            if active_skills:
                self._active_skill_names = [name for name, _ in active_skills]
                skill_block = "\n\n".join(f"### {name}\n{content}" for name, content in active_skills)
                task = f"<learned_feedback>\n{skill_block}\n</learned_feedback>\n\n{task}"
        except Exception:
            pass
        return task

    def _schedule_teardown(self, succeeded: bool | None) -> None:
        """Run verify_cmd + record_run in a background thread (independent of response time)."""
        if not self._active_skill_names:
            return

        skill_names = list(self._active_skill_names)
        cwd = self.cwd
        llm = self.llm
        _succeeded = succeeded

        def _record():
            try:
                from .learner import Learner
                learner = Learner(llm=llm)
                verify_results = learner.run_verify_cmds(skill_names, cwd)
                learner.record_run(skill_names, pytest_passed=_succeeded, verify_results=verify_results)
            except Exception:
                pass

        threading.Thread(target=_record, daemon=True, name="agent-session-teardown").start()

    # ------------------------------------------------------------------
    # Abstract methods — must be implemented by subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def _setup_tools(self) -> list:
        """Return tool list. Channel/queue configuration differs per mode."""

    @abstractmethod
    def _execute(self, prompt: str) -> str | None:
        """Run the agent. Return result string."""

    # ------------------------------------------------------------------
    # Hook methods — override in subclasses as needed
    # ------------------------------------------------------------------

    def _setup_permission_checker(self) -> None:
        """Default: use AgentLoop's built-in permission checker as-is."""

    def _make_progress_hook(self):
        """Default: no progress hook."""
        return None

    def _on_success(self, result: str | None) -> None:
        """Post-processing on success. Default: do nothing."""

    def _on_error(self, error: Exception) -> None:
        """Post-processing on error. Default: do nothing."""


# ---------------------------------------------------------------------------
# Type 1: MCP mode
# ---------------------------------------------------------------------------

class MCPAgentSession(AgentSessionBase):
    """AgentSession for MCP server mode.

    Features:
    - cancel_event: immediately interrupt LLM inference
    - question_queue / reply_queue: bidirectional communication for ask_user_question
    - MCPPermissionChecker: permission requests via MCP channel
    - results/errors delivered via result_queue (caller handles via provided callbacks)
    - progress hook: channel notifications keyed by task_id
    """

    _session_mode = 'gateway'
    _session_kind = 'gateway'

    def __init__(
        self,
        llm: "LLMClientBase",
        cwd: str,
        state,                              # _TaskState (question_queue, reply_queue, result_queue, cancel_event)
        task_id: str,
        notify_fn: Callable,                # (question, options) → None
        notify_running_fn: Callable,        # () → None
        make_progress_hook_fn: Callable,    # (task_id) → hook_fn (prevent circular imports)
        notify_done_fn: Callable,           # (task_id, summary) → None
        notify_error_fn: Callable,          # (task_id, message) → None
        permission_checker=None,            # MCPPermissionChecker instance (DI, prevent circular imports)
        max_turns: int = 200,
        parent_session_id: str | None = None,
        task_mode: str | None = None,
    ):
        from .permissions import PermissionMode
        super().__init__(
            llm=llm,
            cwd=cwd,
            permission_mode=PermissionMode.ACCEPT_EDITS,
            max_turns=max_turns,
            max_context_tokens=_infer_context_size(llm.model),
        )
        self._state = state
        self._task_id = task_id
        self._notify_fn = notify_fn
        self._notify_running_fn = notify_running_fn
        self._make_progress_hook_fn = make_progress_hook_fn
        self._notify_done_fn = notify_done_fn
        self._notify_error_fn = notify_error_fn
        self._permission_checker = permission_checker
        self.parent_session_id = parent_session_id
        self._task_mode = task_mode
        self._emitter_handler = None  # injected after _setup_agent (use set_emitter_handler)
        llm._cancel_event = state.cancel_event

    def _setup_tools(self) -> list:
        from .tools import create_default_tools
        return create_default_tools(
            cwd=self.cwd,
            llm_client=self.llm,
            question_queue=self._state.question_queue,
            reply_queue=self._state.reply_queue,
            notify_fn=self._notify_fn,
            notify_running_fn=self._notify_running_fn,
        )

    def _setup_permission_checker(self) -> None:
        # MCPPermissionChecker is defined in mcp_server.py → DI to avoid circular import
        if self._permission_checker is not None and self._agent is not None:
            self._agent.permission_checker = self._permission_checker

    def _prepare_prompt(self, task: str) -> str:
        prepared = super()._prepare_prompt(task)
        if self._task_mode != "interview":
            return prepared
        interview_contract = (
            "<interaction_contract>\n"
            "- This task requires missing user input before completion.\n"
            "- You MUST call the ask_user_question tool before you continue.\n"
            "- Ask exactly one concise question unless the user answer creates a new blocker.\n"
            "- Do NOT output the question as your final answer.\n"
            "- Do NOT guess missing values.\n"
            "- After the user replies, continue and produce the final answer.\n"
            "</interaction_contract>\n\n"
        )
        return f"{interview_contract}{prepared}"

    def set_emitter_handler(self, handler) -> None:
        """Set emitter event handler. Must be set before calling run()."""
        self._emitter_handler = handler

    def _setup_agent(self) -> None:
        super()._setup_agent()
        if self._emitter_handler is not None and self._agent is not None:
            self._agent.emitter.set_handler(self._emitter_handler)
        # Wire GatewayPermissionChecker YOLO mode change → AgentLoop's PermissionChecker
        if self._permission_checker is not None and self._agent is not None:
            if hasattr(self._permission_checker, 'on_mode_change'):
                agent_checker = getattr(self._agent, 'permission_checker', None)
                if agent_checker is not None and hasattr(agent_checker, 'mode'):
                    self._permission_checker.on_mode_change = lambda m: setattr(agent_checker, 'mode', m)

    def _make_progress_hook(self):
        return self._make_progress_hook_fn(self._task_id)

    def _execute(self, prompt: str) -> str | None:
        assert self._agent is not None
        return self._agent.run(prompt)

    def _on_success(self, result: str | None) -> None:
        self._state.result = result or "[task complete]"
        if self._agent is not None and hasattr(self._agent, "token_totals"):
            self._state.token_totals = dict(self._agent.token_totals)
        self._state.result_queue.put({
            "status": "done",
            "result": self._state.result,
        })
        self._notify_done_fn(
            self._task_id,
            result[:200].replace("\n", " ").strip() if result else None,
        )

    def _on_error(self, error: Exception) -> None:
        error_msg = f"{type(error).__name__}: {error}"
        self._state.result = error_msg
        if self._agent is not None and hasattr(self._agent, "token_totals"):
            self._state.token_totals = dict(self._agent.token_totals)
        self._state.result_queue.put({
            "status": "error",
            "message": error_msg,
        })
        self._notify_error_fn(self._task_id, error_msg)


# ---------------------------------------------------------------------------
# Type 2: Direct CLI terminal execution mode
# ---------------------------------------------------------------------------

class CLIAgentSession(AgentSessionBase):
    """AgentSession for direct CLI terminal execution mode.

    Features:
    - Synchronous execution (direct call, blocking)
    - Optional CLIChannel connection (--channel cli flag)
    - streaming: uses AgentLoop streaming mode
    - Self-learning included (verify_cmd only)
    """

    _session_mode = 'single'
    _session_kind = 'cli'

    _session_mode = 'single'

    def __init__(
        self,
        llm: "LLMClientBase",
        cwd: str,
        permission_mode: "PermissionMode",
        channel=None,               # CLIChannel | None
        max_turns: int = 50,
        max_context_tokens: int = 32000,
        streaming: bool = True,
    ):
        super().__init__(
            llm=llm,
            cwd=cwd,
            permission_mode=permission_mode,
            max_turns=max_turns,
            max_context_tokens=max_context_tokens,
        )
        self._channel = channel
        self._streaming = streaming

    def _setup_tools(self) -> list:
        from .tools import create_default_tools
        kwargs: dict = {}
        if self._channel is not None:
            kwargs["question_queue"] = self._channel.question_queue
            kwargs["reply_queue"] = self._channel.reply_queue
        return create_default_tools(cwd=self.cwd, llm_client=self.llm, **kwargs)

    def _setup_agent(self) -> None:
        super()._setup_agent()
        assert self._agent is not None
        self._agent.streaming = self._streaming

    def _make_progress_hook(self):
        if self._channel is not None:
            return self._channel.make_progress_hook()
        return None

    def _execute(self, prompt: str) -> str | None:
        assert self._agent is not None
        return self._agent.run(prompt)
