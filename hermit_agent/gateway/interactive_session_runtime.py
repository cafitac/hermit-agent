from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, cast

from ._singletons import sse_manager
from .permission import GatewayPermissionChecker
from .sse import SSEEvent
from .task_execution import make_emitter_handler
from ..interactive_prompts import InteractivePrompt, waiting_prompt_snapshot
from ..permissions import PermissionMode
from ..session_logger import SessionLogger
from ..session_store import SessionStore
from ..tools import create_default_tools


class InteractiveAgent(Protocol):
    MAX_TURNS: int
    messages: list[dict]
    turn_count: int
    session_id: str
    emitter: Any
    permission_checker: Any

    def run(self, message: str) -> str: ...
    def _run_loop(self, single_turn: bool = False) -> str: ...


class _RecapLLM(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any: ...


@dataclass
class InteractiveSessionRuntime:
    """Gateway-private long-lived interactive session state.

    This runtime is intentionally private to the gateway layer. Public `/tasks`
    remain task-oriented and must not expose transcript/session continuity.
    """

    session_id: str
    session_dir: str
    cwd: str
    agent: InteractiveAgent
    store: SessionStore
    parent_session_id: str | None = None
    question_queue: queue.Queue = field(default_factory=queue.Queue)
    reply_queue: queue.Queue = field(default_factory=queue.Queue)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    waiting_prompt: InteractivePrompt | None = None
    status: str = "active"
    current_thread: threading.Thread | None = None
    cancel_requested: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def persist(self, *, status: str | None = None) -> None:
        """Persist transcript truth to messages.json and sync meta state."""
        if status is not None:
            self.status = status
        messages = list(getattr(self.agent, "messages", []))
        turn_count = int(getattr(self.agent, "turn_count", 0))
        if turn_count == 0 and self.status in ("completed", "error", "cancelled"):
            import shutil as _shutil
            _shutil.rmtree(self.session_dir, ignore_errors=True)
            return
        self.store.update_transcript_state(
            self.session_dir,
            messages=messages,
            turn_count=turn_count,
            status=self.status,
        )

    def set_waiting_prompt(self, prompt: InteractivePrompt) -> dict[str, object]:
        self.waiting_prompt = prompt
        self.status = "waiting"
        self.persist(status=self.status)
        return waiting_prompt_snapshot(prompt)

    def clear_waiting_prompt(self, *, status: str = "active") -> None:
        self.waiting_prompt = None
        self.status = status
        self.persist(status=self.status)

    def is_waiting_for_reply(self) -> bool:
        return self.status == "waiting" and self.waiting_prompt is not None

    def enqueue_reply(self, message: str) -> None:
        self.reply_queue.put(message)

    def cancel(self) -> None:
        self.cancel_requested = True
        self.cancel_event.set()
        if self.is_waiting_for_reply():
            self.reply_queue.put("__CANCELLED__")


_interactive_sessions: dict[str, InteractiveSessionRuntime] = {}
_interactive_sessions_lock = threading.Lock()


def register_interactive_session(runtime: InteractiveSessionRuntime) -> InteractiveSessionRuntime:
    with _interactive_sessions_lock:
        _interactive_sessions[runtime.session_id] = runtime
    sse_manager.register(runtime.session_id)
    return runtime


def get_interactive_session(session_id: str) -> InteractiveSessionRuntime | None:
    with _interactive_sessions_lock:
        return _interactive_sessions.get(session_id)


def delete_interactive_session(session_id: str) -> None:
    with _interactive_sessions_lock:
        _interactive_sessions.pop(session_id, None)


def _build_interactive_runtime(
    *,
    session_id: str,
    cwd: str,
    llm,
    store: SessionStore,
    parent_session_id: str | None,
    permission_mode: PermissionMode,
    agent_factory: Callable[..., InteractiveAgent] | None,
    loaded_messages: list[dict] | None = None,
    loaded_turn_count: int = 0,
    loaded_status: str = "active",
) -> InteractiveSessionRuntime:
    from ..loop import AgentLoop

    runtime_ref: dict[str, InteractiveSessionRuntime] = {}
    question_queue: queue.Queue = queue.Queue()
    reply_queue: queue.Queue = queue.Queue()
    cancel_event = threading.Event()

    def _waiting_notify(question: str, options: list, *, tool_name: str = "ask", method: str = "") -> None:
        runtime = runtime_ref["runtime"]
        prompt = InteractivePrompt(
            task_id=session_id,
            question=question,
            options=tuple(options or ()),
            prompt_kind="waiting",
            tool_name=tool_name or "ask",
            method=method,
        )
        snapshot = runtime.set_waiting_prompt(prompt)
        sse_manager.publish_threadsafe(
            session_id,
            SSEEvent(
                type="waiting",
                question=question,
                options=cast(list[str], snapshot["options"]),
                tool_name=str(snapshot["tool_name"]),
                method=str(snapshot.get("method", "")),
            ),
        )

    def _notify_running() -> None:
        runtime = runtime_ref["runtime"]
        runtime.clear_waiting_prompt(status="running")
        sse_manager.publish_threadsafe(session_id, SSEEvent(type="reply_ack", message="reply received"))

    tools = create_default_tools(
        cwd=cwd,
        llm_client=llm,
        question_queue=question_queue,
        reply_queue=reply_queue,
        notify_fn=_waiting_notify,
        notify_running_fn=_notify_running,
    )
    factory = agent_factory or AgentLoop
    agent = factory(
        llm=llm,
        tools=tools,
        cwd=cwd,
        permission_mode=permission_mode,
        session_id=session_id,
        session_kind="interactive",
    )
    # Interactive sessions rely on compaction for long runs — no hard turn cap.
    agent.MAX_TURNS = 9999
    logger = SessionLogger(session_dir=store.find_session_dir(session_id, "interactive", cwd) or "")
    llm.session_logger = logger
    if hasattr(agent, "emitter"):
        agent.emitter.session_logger = logger
        agent.emitter.set_handler(make_emitter_handler(session_id, sse_manager))
    checker = GatewayPermissionChecker(
        mode=permission_mode,
        question_queue=question_queue,
        reply_queue=reply_queue,
        notify_fn=_waiting_notify,
        notify_running_fn=_notify_running,
    )
    if hasattr(agent, "permission_checker"):
        agent.permission_checker = checker
    llm._cancel_event = cancel_event
    if loaded_messages is not None:
        agent.messages = list(loaded_messages)
        agent.turn_count = loaded_turn_count
    runtime = InteractiveSessionRuntime(
        session_id=session_id,
        session_dir=store.find_session_dir(session_id, "interactive", cwd) or "",
        cwd=cwd,
        agent=agent,
        store=store,
        parent_session_id=parent_session_id,
        question_queue=question_queue,
        reply_queue=reply_queue,
        cancel_event=cancel_event,
        status=loaded_status,
    )
    runtime_ref["runtime"] = runtime
    return runtime


def create_interactive_session_runtime(
    *,
    session_id: str | None,
    cwd: str,
    llm,
    tools: list | None = None,
    store: SessionStore | None = None,
    parent_session_id: str | None = None,
    permission_mode: PermissionMode = PermissionMode.ACCEPT_EDITS,
    agent_factory: Callable[..., InteractiveAgent] | None = None,
) -> InteractiveSessionRuntime:
    """Create a fresh private interactive session runtime."""
    store = store or SessionStore()
    resolved_session_id = session_id or uuid.uuid4().hex[:12]
    session_dir = store.create_session(
        mode="interactive",
        session_id=resolved_session_id,
        cwd=cwd,
        model=getattr(llm, "model", None),
        parent_session_id=parent_session_id,
    )
    runtime = _build_interactive_runtime(
        session_id=resolved_session_id,
        cwd=cwd,
        llm=llm,
        store=store,
        parent_session_id=parent_session_id,
        permission_mode=permission_mode,
        agent_factory=agent_factory,
    )
    runtime.session_dir = session_dir
    runtime.persist()
    return register_interactive_session(runtime)


def load_interactive_session_runtime(
    *,
    session_id: str,
    cwd: str,
    llm,
    tools: list | None = None,
    store: SessionStore | None = None,
    permission_mode: PermissionMode = PermissionMode.ACCEPT_EDITS,
    agent_factory: Callable[..., InteractiveAgent] | None = None,
) -> InteractiveSessionRuntime:
    """Rebuild an interactive runtime from persisted transcript state."""
    store = store or SessionStore()
    loaded = store.load_session(session_id, mode="interactive", cwd=cwd)
    if loaded is None:
        raise FileNotFoundError(f"interactive session not found: {session_id}")
    raw_meta = loaded.get("meta") or {}
    runtime = _build_interactive_runtime(
        session_id=session_id,
        cwd=cwd,
        llm=llm,
        store=store,
        parent_session_id=raw_meta.get("parent_session_id"),
        permission_mode=permission_mode,
        agent_factory=agent_factory,
        loaded_messages=list(loaded.get("messages") or []),
        loaded_turn_count=int(raw_meta.get("turn_count", 0)),
        loaded_status=str(raw_meta.get("status", "active") or "active"),
    )
    session_dir = store.find_session_dir(session_id, "interactive", cwd)
    if session_dir is None:
        raise FileNotFoundError(f"interactive session directory not found: {session_id}")
    runtime.session_dir = session_dir
    return register_interactive_session(runtime)


def _handle_resume_selector(runtime: InteractiveSessionRuntime) -> str:
    """Show interactive session picker for /resume with no args."""
    import time as _time
    from ..session import list_sessions, load_session

    sessions = list_sessions(limit=100)
    if not sessions:
        return "No saved sessions."

    sessions = sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    def _age(updated_at: float) -> str:
        age = _time.time() - updated_at
        if age < 3600:
            return f"{int(age / 60)}m ago"
        if age < 86400:
            return f"{int(age / 3600)}h ago"
        return f"{int(age / 86400)}d ago"

    def _session_label(s: object) -> str:
        sid = getattr(s, "session_id", "")
        turns = getattr(s, "turn_count", 0)
        age = _age(getattr(s, "updated_at", 0.0))
        recap = getattr(s, "recap", "") or ""
        preview = getattr(s, "preview", "") or ""
        description = (recap or preview)[:60]
        return f"{sid} | {turns} turns | {age} | {description}"

    options = [
        _session_label(s)
        for s in sessions
        if getattr(s, "turn_count", 0) > 0
    ]
    options.append("Cancel")

    question = "Select a session to resume:"
    prompt = InteractivePrompt(
        task_id=runtime.session_id,
        question=question,
        options=tuple(options),
        prompt_kind="waiting",
        tool_name="select",
        method="select",
    )
    runtime.set_waiting_prompt(prompt)
    sse_manager.publish_threadsafe(
        runtime.session_id,
        SSEEvent(type="waiting", question=question, options=options, tool_name="select", method="select"),
    )

    reply: str = runtime.reply_queue.get()
    runtime.clear_waiting_prompt(status="running")
    sse_manager.publish_threadsafe(runtime.session_id, SSEEvent(type="reply_ack", message="reply received"))

    if reply in ("__CANCELLED__", "Cancel"):
        return "Resume cancelled."

    selected_id = reply.split(" | ")[0].strip()
    saved = load_session(selected_id)
    if saved:
        runtime.agent.messages = saved.messages
        runtime.agent.session_id = saved.meta.session_id
        runtime.agent.turn_count = saved.meta.turn_count
        header = f"[Resumed: {saved.meta.session_id} | {saved.meta.turn_count} turns]"
        recap = (saved.meta.recap or "").strip()
        history = _format_full_history(saved.messages)
        parts = [header]
        if recap:
            parts.append(f"\nSummary: {recap}")
        if history:
            parts.append(f"\n--- Conversation history ---\n{history}")
        return "\n".join(parts)
    return f"Session not found: {selected_id}"


def _extract_text(content: object) -> str:
    """Extract plain text from a message content (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return " ".join(parts)
    return ""


def _format_full_history(messages: list[dict]) -> str:
    """Format the complete conversation history for display after resume."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        text = _extract_text(msg.get("content")).strip()
        if not text:
            continue
        if role == "user":
            lines.append(f"You: {text}")
        elif role == "assistant":
            lines.append(f"Agent: {text}")
        lines.append("")
    return "\n".join(lines).rstrip()


_RECAP_MIN_TURNS = 3
_RECAP_MSG_LIMIT = 20
_RECAP_CONTENT_LIMIT = 500


def _generate_session_recap(messages: list[dict], llm: _RecapLLM) -> str:
    """Call the LLM to produce a 2-3 sentence recap of the session."""
    try:
        tail = messages[-_RECAP_MSG_LIMIT:]
        lines: list[str] = []
        for m in tail:
            role = m.get("role", "")
            content = str(m.get("content") or "")[:_RECAP_CONTENT_LIMIT]
            lines.append(f"{role}: {content}")
        conversation = "\n".join(lines)
        prompt = (
            "다음 대화를 2~3문장으로 요약해줘. "
            "어떤 작업을 했고 어떤 결과가 나왔는지 핵심만 한국어로 작성해줘.\n\n"
            f"{conversation}"
        )
        response = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=[],
        )
        return (response.content or "").strip()
    except Exception:
        return ""


def _save_recap_async(runtime: InteractiveSessionRuntime) -> None:
    """Spawn a daemon thread to generate and persist a session recap."""
    turn_count = int(getattr(runtime.agent, "turn_count", 0))
    if turn_count < _RECAP_MIN_TURNS:
        return
    messages = list(getattr(runtime.agent, "messages", []))
    llm = getattr(runtime.agent, "llm", None)
    if not messages or llm is None:
        return

    def _worker() -> None:
        try:
            recap = _generate_session_recap(messages, llm)
            if recap:
                runtime.store.update_meta(runtime.session_dir, recap=recap)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True, name=f"recap-{runtime.session_id}").start()


def submit_interactive_turn(runtime: InteractiveSessionRuntime, message: str) -> str:
    """Submit a user turn to a private interactive runtime."""
    with runtime._lock:
        if runtime.status == "waiting":
            raise RuntimeError("Interactive session is waiting for a reply.")
        if runtime.current_thread is not None and runtime.current_thread.is_alive():
            raise RuntimeError("Interactive session is already running.")
        sse_manager.register(runtime.session_id)
        runtime.cancel_requested = False
        runtime.cancel_event.clear()
        runtime.status = "running"
        runtime.persist(status="running")

        def _run() -> None:
            try:
                # /resume with no args → interactive session picker
                stripped = message.strip()
                if stripped == "/resume":
                    result = _handle_resume_selector(runtime)
                else:
                    from ..loop import AgentLoop, handle_slash_command, TRIGGER_AGENT, TRIGGER_AGENT_SINGLE
                    agent_loop = cast(AgentLoop, runtime.agent)
                    slash_result = handle_slash_command(agent_loop, message)
                    if slash_result is None:
                        result = runtime.agent.run(message)
                    elif slash_result in (TRIGGER_AGENT, TRIGGER_AGENT_SINGLE):
                        single = slash_result == TRIGGER_AGENT_SINGLE
                        result = agent_loop._run_loop(single_turn=single)
                    else:
                        result = slash_result
                if runtime.cancel_requested or runtime.cancel_event.is_set():
                    runtime.clear_waiting_prompt(status="cancelled")
                    sse_manager.publish_threadsafe(runtime.session_id, SSEEvent(type="cancelled", message="Interactive session cancelled"))
                elif runtime.is_waiting_for_reply():
                    runtime.persist(status="waiting")
                else:
                    runtime.persist(status="completed")
                    _save_recap_async(runtime)
                    sse_manager.publish_threadsafe(runtime.session_id, SSEEvent(type="done", result=result or ""))
            except Exception as exc:
                if runtime.cancel_requested or runtime.cancel_event.is_set():
                    runtime.clear_waiting_prompt(status="cancelled")
                    sse_manager.publish_threadsafe(runtime.session_id, SSEEvent(type="cancelled", message="Interactive session cancelled"))
                else:
                    runtime.persist(status="error")
                    sse_manager.publish_threadsafe(runtime.session_id, SSEEvent(type="error", message=f"{type(exc).__name__}: {exc}"))
            finally:
                runtime.current_thread = None

        runtime.current_thread = threading.Thread(target=_run, daemon=True, name=f"interactive-session-{runtime.session_id}")
        runtime.current_thread.start()
        return runtime.status


def reply_to_interactive_session(runtime: InteractiveSessionRuntime, message: str) -> None:
    if not runtime.is_waiting_for_reply():
        raise RuntimeError("Interactive session is not waiting for a reply.")
    runtime.enqueue_reply(message)


def cancel_interactive_session(runtime: InteractiveSessionRuntime) -> None:
    runtime.cancel()
