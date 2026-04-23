from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from typing import Any

import httpx
import mcp.types as mcp_types
from mcp.shared.message import SessionMessage
from mcp.shared.experimental.tasks.capabilities import has_task_augmented_elicitation
from mcp.types import JSONRPCMessage, JSONRPCNotification

from .codex_app_server_bridge import get_attached_codex_app_server_transport
from .codex_channels_adapter import (
    CodexChannelsWaitSession,
    build_interaction,
    load_codex_channels_settings,
)
from .config import load_settings
from .interactive_prompts import build_codex_channels_interaction, create_interactive_prompt
from .interaction_presenter import present_interaction
from .interactive_sinks import (
    ClaudeMcpInteractiveSink,
    CodexChannelsInteractiveSink,
    CodexAppServerTransport,
    InteractivePromptSink,
    build_codex_app_server_sink,
    compose_interactive_prompt_sinks,
)

_LOG_PATH = os.path.expanduser("~/.hermit/mcp_server.log")


def _log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
            f.flush()
    except Exception:
        pass


_current_session = None  # type: ignore[assignment]
_current_loop = None     # type: ignore[assignment]
_session_lock = threading.Lock()
_pending_channel_notifications: list[tuple[str, dict]] = []
_task_contexts: dict[str, dict[str, str]] = {}
_task_contexts_lock = threading.Lock()
_visible_prompt_notifications: dict[str, str] = {}
_visible_prompt_notifications_lock = threading.Lock()


async def _send_channel_notification(session, content: str, meta: dict) -> None:
    notif = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/claude/channel",
        params={"content": content, "meta": meta},
    )
    _log(f"[channel] -> write_stream.send type={meta.get('kind')} task={str(meta.get('task_id',''))[:8]}")
    await session._write_stream.send(SessionMessage(message=JSONRPCMessage(notif)))
    _log(f"[channel] <- write_stream.send ok type={meta.get('kind')}")


def _schedule_channel_send(loop, session, content: str, meta: dict) -> None:
    async def _send() -> None:
        await _send_channel_notification(session, content, meta)

    def _runner() -> None:
        task = asyncio.create_task(_send())

        def _done_callback(done_task: asyncio.Task) -> None:
            try:
                done_task.result()
            except Exception as e:
                _log(f"[channel] buffered send failed: {e}")

        task.add_done_callback(_done_callback)

    loop.call_soon_threadsafe(_runner)


def _flush_pending_channel_notifications(session, loop) -> None:
    with _session_lock:
        pending = list(_pending_channel_notifications)
        _pending_channel_notifications.clear()

    if not pending:
        return

    for content, meta in pending:
        _log(f"[channel] flushing buffered notification type={meta.get('kind')} task={str(meta.get('task_id',''))[:8]}")
        _schedule_channel_send(loop, session, content, meta)


def _set_active_session(session, loop) -> None:
    global _current_session, _current_loop
    with _session_lock:
        _current_session = session
        _current_loop = loop
    client_caps = getattr(getattr(session, "client_params", None), "capabilities", None)
    task_augmented_elicitation = False
    try:
        if client_caps is not None:
            task_augmented_elicitation = has_task_augmented_elicitation(client_caps)
    except Exception:
        task_augmented_elicitation = False
    _log(
        f"[channel] active session attached type={type(session).__name__} "
        f"send_request={hasattr(session, 'send_request')} "
        f"task_augmented_elicitation={task_augmented_elicitation}"
    )
    _flush_pending_channel_notifications(session, loop)


def _fire_channel_notification_sync(content: str, meta: dict) -> None:
    with _session_lock:
        session = _current_session
        loop = _current_loop
    if session is None or loop is None:
        with _session_lock:
            _pending_channel_notifications.append((content, meta))
        _log(f"[channel] no active session/loop — notification buffered type={meta.get('kind')}")
        return
    _log(f"[channel] scheduling coroutine type={meta.get('kind')} task={str(meta.get('task_id',''))[:8]}")
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _send_channel_notification(session, content, meta),
            loop,
        )
        fut.result(timeout=5)
        _log(f"[channel] coroutine completed type={meta.get('kind')}")
    except Exception as e:
        _log(f"[channel] send failed: {e}")


def _current_cwd() -> str:
    return os.getcwd()


def _remember_task_context(task_id: str, cwd: str) -> None:
    with _task_contexts_lock:
        _task_contexts[task_id] = {"cwd": cwd}


def _forget_task_context(task_id: str) -> None:
    with _task_contexts_lock:
        _task_contexts.pop(task_id, None)


def _task_cwd(task_id: str) -> str:
    with _task_contexts_lock:
        context = _task_contexts.get(task_id, {})
    return context.get("cwd", _current_cwd())


def _notify_visible_prompt(*, task_id: str, question: str, options: list[str], prompt_kind: str) -> None:
    normalized_question = question.strip()
    normalized_options = [option.strip() for option in options if option.strip()]
    fingerprint = f"{prompt_kind}|{normalized_question}|{'|'.join(normalized_options)}"
    with _visible_prompt_notifications_lock:
        if _visible_prompt_notifications.get(task_id) == fingerprint:
            return
        _visible_prompt_notifications[task_id] = fingerprint

    presented = present_interaction(question=normalized_question, options=normalized_options, prompt_kind=prompt_kind)
    title = presented.title
    body = f"{presented.body}\n{presented.options_line}"[:240]
    try:
        if os.uname().sysname == "Darwin":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{body.replace(chr(34), chr(39))}" with title "{title.replace(chr(34), chr(39))}"',
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
    except Exception:
        return


def _clear_visible_prompt_notification(task_id: str) -> None:
    with _visible_prompt_notifications_lock:
        _visible_prompt_notifications.pop(task_id, None)


def _gateway_reply(task_id: str, message: str) -> bool:
    cfg = load_settings(cwd=_task_cwd(task_id))
    gateway_url = str(cfg.get("gateway_url") or "http://127.0.0.1:8765").rstrip("/")
    gateway_api_key = cfg.get("gateway_api_key") or ""
    headers = {"Content-Type": "application/json"}
    if gateway_api_key:
        headers["Authorization"] = f"Bearer {gateway_api_key}"
    try:
        response = httpx.post(
            f"{gateway_url}/tasks/{task_id}/reply",
            json={"message": message},
            headers=headers,
            timeout=10.0,
        )
        if response.status_code == 200:
            _log(f"[codex-channels] replied task={task_id[:8]}")
            return True
        _log(f"[codex-channels] reply failed task={task_id[:8]} status={response.status_code}")
        return False
    except Exception as exc:
        _log(f"[codex-channels] reply error task={task_id[:8]} err={exc}")
        return False


def _build_codex_channels_wait_interaction(prompt) -> dict:
    return build_codex_channels_interaction(prompt)


def _load_codex_channels_wait_settings(prompt):
    cwd = _task_cwd(prompt.task_id)
    cfg = load_settings(cwd=cwd)
    return load_codex_channels_settings(cfg, cwd)


_claude_mcp_sink = ClaudeMcpInteractiveSink(
    notify=lambda content, meta: _fire_channel_notification_sync(content, meta),
)
_codex_channels_sink = CodexChannelsInteractiveSink(
    settings_loader=_load_codex_channels_wait_settings,
    session_factory=lambda **kwargs: CodexChannelsWaitSession(**kwargs),
    interaction_builder=_build_codex_channels_wait_interaction,
    reply_callback=lambda prompt, answer: _gateway_reply(prompt.task_id, answer),
    thread_factory=lambda **kwargs: threading.Thread(**kwargs),
    log_fn=_log,
)


_default_interactive_sink = compose_interactive_prompt_sinks(
    _claude_mcp_sink,
    _codex_channels_sink,
)


def _build_session_elicitation_request(prompt):
    presented = present_interaction(
        question=prompt.question,
        options=list(prompt.options),
        prompt_kind=prompt.prompt_kind,
    )
    answer_schema: dict[str, Any] = {
        "type": "string",
        "title": "Answer",
    }
    if prompt.options:
        answer_schema["enum"] = list(prompt.options)

    requested_schema = {
        "type": "object",
        "properties": {
            "answer": answer_schema,
        },
        "required": ["answer"],
        "additionalProperties": False,
    }
    return mcp_types.ElicitRequest(
        params=mcp_types.ElicitRequestFormParams(
            message=presented.body,
            requestedSchema=requested_schema,
        )
    )


def _extract_elicitation_answer(prompt, result: mcp_types.ElicitResult) -> str:
    if result.action == "cancel":
        return "cancel"
    if result.action == "decline":
        return "No" if prompt.prompt_kind == "permission_ask" else "cancel"
    content = result.content or {}
    if isinstance(content, dict) and content.get("answer") is not None:
        return str(content["answer"])
    if prompt.options:
        return str(prompt.options[0])
    return ""


class _SessionCodexAppServerSink:
    def __init__(self, *, session, loop, reply_callback, fallback_sink, log_fn) -> None:
        self._session = session
        self._loop = loop
        self._reply_callback = reply_callback
        self._fallback_sink = fallback_sink
        self._log = log_fn
        self._pending: dict[str, Any] = {}
        self._lock = threading.Lock()

    def notify(self, prompt) -> None:
        self.clear(prompt.task_id)
        request = _build_session_elicitation_request(prompt)
        client_caps = getattr(getattr(self._session, "client_params", None), "capabilities", None)
        use_task_augmented = False
        try:
            if client_caps is not None:
                use_task_augmented = has_task_augmented_elicitation(client_caps)
        except Exception:
            use_task_augmented = False

        async def _send_and_bridge() -> None:
            try:
                if use_task_augmented:
                    result = await self._session.experimental.elicit_as_task(
                        prompt.question,
                        request.params.requestedSchema,
                    )
                    method_name = "elicitation/create(task)"
                else:
                    result = await self._session.send_request(
                        request,
                        mcp_types.ElicitResult,
                    )
                    method_name = "elicitation/create"
                self._log(
                    f"[codex-session] elicitation result task={prompt.task_id[:8]} "
                    f"action={result.action} content={result.content!r}"
                )
                answer = _extract_elicitation_answer(prompt, result)
                self._reply_callback(prompt.task_id, answer)
                self._log(
                    f"[codex-session] replied task={prompt.task_id[:8]} "
                    f"method={method_name}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log(
                    f"[codex-session] request failed task={prompt.task_id[:8]} "
                    f"method={'elicitation/create(task)' if use_task_augmented else 'elicitation/create'} err={exc}"
                )
                self._fallback_sink.notify(prompt)
            finally:
                with self._lock:
                    self._pending.pop(prompt.task_id, None)

        future = asyncio.run_coroutine_threadsafe(_send_and_bridge(), self._loop)
        with self._lock:
            self._pending[prompt.task_id] = future
        self._log(
            f"[codex-session] request sent task={prompt.task_id[:8]} "
            f"method={'elicitation/create(task)' if use_task_augmented else 'elicitation/create'}"
        )

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        with self._lock:
            future = self._pending.pop(task_id, None)
        if future is not None:
            future.cancel()


def _build_session_app_server_sink():
    disable_env = str(os.environ.get("HERMIT_DISABLE_CODEX_SESSION_ELICITATION", "")).strip().lower()
    if disable_env in {"1", "true", "yes"}:
        return None
    with _session_lock:
        session = _current_session
        loop = _current_loop
    if session is None or loop is None or not hasattr(session, "send_request"):
        return None
    return _SessionCodexAppServerSink(
        session=session,
        loop=loop,
        reply_callback=lambda task_id, answer: _gateway_reply(task_id, answer),
        fallback_sink=_codex_channels_sink,
        log_fn=_log,
    )


def _has_host_visible_prompt_surface() -> bool:
    if get_attached_codex_app_server_transport() is not None:
        return True
    with _session_lock:
        return _current_session is not None and _current_loop is not None


def _build_interactive_sink(
    *,
    app_server_sink: InteractivePromptSink | None = None,
    app_server_transport: CodexAppServerTransport | None = None,
    app_server_line_writer=None,
    app_server_stream=None,
    app_server_stream_lock=None,
    include_codex_channels: bool | None = None,
):
    attached_transport = None
    if (
        app_server_sink is None
        and app_server_transport is None
        and app_server_line_writer is None
        and app_server_stream is None
    ):
        attached_transport = get_attached_codex_app_server_transport()
    resolved_app_server_sink = app_server_sink or build_codex_app_server_sink(
        transport=app_server_transport or attached_transport,
        line_writer=app_server_line_writer,
        stream=app_server_stream,
        stream_lock=app_server_stream_lock,
        log_fn=_log,
    )
    if include_codex_channels is None:
        include_codex_channels = resolved_app_server_sink is None
    sinks: list[InteractivePromptSink] = [_claude_mcp_sink]
    if include_codex_channels:
        sinks.append(_codex_channels_sink)
    return compose_interactive_prompt_sinks(
        *sinks,
        optional_sink=resolved_app_server_sink,
    )


_codex_channel_waits = _codex_channels_sink.sessions
_codex_channel_waits_lock = _codex_channels_sink.lock


def _current_interactive_sink():
    session_sink = _build_session_app_server_sink()
    if session_sink is not None:
        return _build_interactive_sink(
            app_server_sink=session_sink,
            include_codex_channels=False,
        )
    if get_attached_codex_app_server_transport() is not None:
        return _build_interactive_sink(include_codex_channels=False)
    return _default_interactive_sink


def _stop_codex_channels_wait(task_id: str, *, expected: CodexChannelsWaitSession | None = None) -> None:
    _codex_channels_sink.clear(task_id, expected=expected)


def _bridge_codex_channels_reply(task_id: str, session: CodexChannelsWaitSession, *, poll_interval: float = 0.25) -> None:
    prompt = create_interactive_prompt(task_id=task_id, question="", options=[])
    _codex_channels_sink._bridge_reply(prompt, session, poll_interval=poll_interval)


def _notify_channel(
    task_id: str,
    question: str,
    options: list[str],
    *,
    prompt_kind: str = "waiting",
    tool_name: str = "",
    method: str = "",
) -> None:
    if not _has_host_visible_prompt_surface():
        _notify_visible_prompt(
            task_id=task_id,
            question=question,
            options=options,
            prompt_kind=prompt_kind,
        )
    prompt = create_interactive_prompt(
        task_id=task_id,
        question=question,
        options=options,
        prompt_kind=prompt_kind,
        tool_name=tool_name,
        method=method,
    )
    _current_interactive_sink().notify(prompt)


def _notify_done(task_id: str, message: str | None = None) -> None:
    meta = {"task_id": task_id, "kind": "done"}
    _fire_channel_notification_sync(message or "task done", meta)
    _stop_codex_channels_wait(task_id)
    _clear_visible_prompt_notification(task_id)
    _forget_task_context(task_id)


def _notify_reply(task_id: str, message: str) -> None:
    meta = {"task_id": task_id, "kind": "reply"}
    _fire_channel_notification_sync(message, meta)


def _notify_error(task_id: str, message: str) -> None:
    meta = {"task_id": task_id, "kind": "error"}
    _fire_channel_notification_sync(message, meta)
    _stop_codex_channels_wait(task_id)
    _clear_visible_prompt_notification(task_id)
    _forget_task_context(task_id)


def _notify_running(task_id: str) -> None:
    _fire_channel_notification_sync(
        "task running",
        {"task_id": task_id, "kind": "running"},
    )
    _stop_codex_channels_wait(task_id)
    _clear_visible_prompt_notification(task_id)
