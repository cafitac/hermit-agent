from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..interactive_prompts import InteractivePrompt


def maybe_start_codex_channels_wait_session(
    prompt: InteractivePrompt,
    *,
    settings: Any,
    session_factory: Callable[..., Any],
    interaction_builder: Callable[[InteractivePrompt], dict[str, Any]],
) -> Any | None:
    if not getattr(settings, "enabled", False):
        return None

    try:
        session = session_factory(
            settings=settings,
            interaction=interaction_builder(prompt),
        )
        session.start()
        return session
    except Exception:
        return None


class CodexChannelsInteractiveSink:
    def __init__(
        self,
        *,
        settings_loader: Callable[[InteractivePrompt], Any],
        session_factory: Callable[..., Any],
        interaction_builder: Callable[[InteractivePrompt], dict[str, Any]],
        reply_callback: Callable[[InteractivePrompt, str], object],
        thread_factory: Callable[..., Any] = threading.Thread,
        sleep_fn: Callable[[float], None] = time.sleep,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._settings_loader = settings_loader
        self._session_factory = session_factory
        self._interaction_builder = interaction_builder
        self._reply_callback = reply_callback
        self._thread_factory = thread_factory
        self._sleep_fn = sleep_fn
        self._log = log_fn or (lambda _line: None)
        self.sessions: dict[str, Any] = {}
        self.lock = threading.Lock()

    def notify(self, prompt: InteractivePrompt) -> None:
        settings = self._settings_loader(prompt)
        session = maybe_start_codex_channels_wait_session(
            prompt,
            settings=settings,
            session_factory=self._session_factory,
            interaction_builder=self._interaction_builder,
        )
        if session is None:
            return

        self.clear(prompt.task_id)
        with self.lock:
            self.sessions[prompt.task_id] = session

        thread = self._thread_factory(
            target=self._bridge_reply,
            args=(prompt, session),
            name=f"codex-channels-mcp-{prompt.task_id[:8]}",
            daemon=True,
        )
        thread.start()
        self._log(f"[codex-channels] wait started task={prompt.task_id[:8]}")

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        with self.lock:
            session = self.sessions.get(task_id)
            if session is None:
                return
            if expected is not None and session is not expected:
                return
            self.sessions.pop(task_id, None)
        try:
            session.terminate()
        except Exception as exc:
            self._log(f"[codex-channels] terminate error task={task_id[:8]} err={exc}")

    def _bridge_reply(
        self,
        prompt: InteractivePrompt,
        session: Any,
        *,
        poll_interval: float = 0.25,
    ) -> None:
        try:
            while True:
                with self.lock:
                    active = self.sessions.get(prompt.task_id)
                if active is not session:
                    return
                answer = session.poll_response()
                if answer is not None:
                    self._reply_callback(prompt, str(answer))
                    return
                self._sleep_fn(poll_interval)
        finally:
            self.clear(prompt.task_id, expected=session)
