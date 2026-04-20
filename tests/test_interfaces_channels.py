from __future__ import annotations

import queue

import pytest

from hermit_agent.interfaces.base import ChannelInterface
from hermit_agent.interfaces.cli import CLIChannel
from hermit_agent.interfaces.http import HTTPChannel
from hermit_agent.interfaces.telegram import TelegramChannel


class _StubChannel(ChannelInterface):
    def __init__(self):
        super().__init__()
        self.presented: list[tuple[str, list[str]]] = []

    def send(self, message: str) -> None:
        pass

    def _present_question(self, question: str, options: list[str]) -> str:
        self.presented.append((question, options))
        return "answer"


def test_channel_base_answer_loop_moves_replies_through_queue():
    channel = _StubChannel()
    channel.question_queue.put({"question": "Continue?", "options": ["Yes", "No"]})
    channel.question_queue.put(None)

    channel._answer_loop()

    assert channel.presented == [("Continue?", ["Yes", "No"])]
    assert channel.reply_queue.get_nowait() == "answer"


def test_cli_channel_presents_question_and_collects_input(monkeypatch):
    channel = CLIChannel()
    monkeypatch.setattr("builtins.input", lambda _prompt: "  yes  ")

    answer = channel._present_question("Continue?", ["Yes", "No"])

    assert answer == "yes"


def test_http_channel_presents_question_via_notify_and_poll(monkeypatch):
    channel = HTTPChannel(task_id="task-1", channel_url="http://127.0.0.1:8789")
    seen: list[tuple[str, str, list[str] | None]] = []
    monkeypatch.setattr(
        channel,
        "notify",
        lambda event_type, **kwargs: seen.append((event_type, kwargs.get("question", ""), kwargs.get("options"))),
    )
    monkeypatch.setattr(channel, "_poll_for_answer", lambda: "approved")

    answer = channel._present_question("Allow?", ["Yes", "No"])

    assert answer == "approved"
    assert seen == [("waiting", "Allow?", ["Yes", "No"])]


def test_telegram_channel_returns_skip_when_send_fails(monkeypatch):
    channel = TelegramChannel(bot_token="token", chat_id="123")
    monkeypatch.setattr(channel, "_send_message", lambda _text: (_ for _ in ()).throw(RuntimeError("boom")))

    answer = channel._present_question("Allow?", ["Yes", "No"])

    assert answer == "skip"


def test_telegram_channel_sends_question_and_waits_for_reply(monkeypatch):
    channel = TelegramChannel(bot_token="token", chat_id="123")
    sent: list[str] = []
    monkeypatch.setattr(channel, "_send_message", lambda text: sent.append(text))
    monkeypatch.setattr(channel, "_wait_for_reply", lambda: "approved")

    answer = channel._present_question("Allow?", ["Yes", "No"])

    assert answer == "approved"
    assert sent
    assert "Allow?" in sent[0]
    assert "1. Yes" in sent[0]


def test_channel_progress_hook_reports_only_selected_tools():
    sent: queue.Queue[str] = queue.Queue()

    class _ProgressChannel(ChannelInterface):
        def send(self, message: str) -> None:
            sent.put(message)

        def _present_question(self, question: str, options: list[str]) -> str:
            return "ok"

    hook = _ProgressChannel().make_progress_hook()
    hook("bash_tool", "line1\nline2", False)
    hook("read_file", "ignored", False)

    assert sent.get_nowait().startswith("▶ bash_tool:")
    assert sent.empty()
