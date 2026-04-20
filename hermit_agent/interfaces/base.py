"""ChannelInterface — abstract base class for HermitAgent external communication channels."""
from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from typing import Callable


class ChannelInterface(ABC):
    """HermitAgent ↔ user communication channel interface.

    Implementations:
      - CLIChannel: terminal stdin/stdout
      - TelegramChannel: Telegram Bot API (raw HTTP)
      - HTTPChannel: hermit-channel server integration

    Usage example:
        channel = CLIChannel()
        tools = create_default_tools(
            question_queue=channel.question_queue,
            reply_queue=channel.reply_queue,
            notify_fn=channel.make_notify_fn(),
        )
        agent = AgentLoop(
            ...,
            on_tool_result=channel.make_progress_hook(),
        )
        channel.start()
        agent.run(task)
        channel.stop()
    """

    def __init__(self) -> None:
        self.question_queue: queue.Queue = queue.Queue()
        self.reply_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── required abstract methods ──────────────────────────────────────────────────────

    @abstractmethod
    def send(self, message: str) -> None:
        """Deliver progress updates, completion results, etc. to the user."""

    @abstractmethod
    def _present_question(self, question: str, options: list[str]) -> str:
        """Deliver one question to the concrete transport and return the answer."""

    def _answer_loop(self) -> None:
        """Loop that pulls questions from question_queue and records replies."""
        while not self._stop_event.is_set():
            try:
                qdata = self.question_queue.get(timeout=0.5)
            except Exception:
                continue

            if qdata is None:
                break

            question = qdata.get("question", "")
            options: list[str] = qdata.get("options", [])
            answer = self._present_question(question, options)
            self.reply_queue.put(answer)

    # ── common methods ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the answer_loop thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._answer_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shut down the channel."""
        self._stop_event.set()
        # inject sentinel to unblock queue.get()
        self.question_queue.put(None)

    def make_notify_fn(self) -> Callable[[str, list], None]:
        """Callback for AskUserQuestionTool.notify_fn.

        Unlike MCP mode, CLI/Telegram handle questions directly in answer_loop,
        so notify_fn can be returned as a no-op.
        (Override in subclass if needed)
        """
        def _noop(question: str, options: list) -> None:
            pass
        return _noop

    def make_progress_hook(self) -> Callable[[str, str, bool], None]:
        """Callback for AgentLoop.on_tool_result.

        Default implementation: forwards only reportable tools via self.send().
        Subclasses can override to add throttling etc.
        """
        REPORT_TOOLS = {"bash_tool", "run_tests"}

        def hook(tool_name: str, result: str, is_error: bool) -> None:
            if tool_name not in REPORT_TOOLS:
                return
            summary = result[:300].replace("\n", " ").strip()
            prefix = "⚠️" if is_error else "▶"
            self.send(f"{prefix} {tool_name}: {summary}")

        return hook
