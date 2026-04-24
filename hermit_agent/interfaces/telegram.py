"""TelegramChannel — Telegram Bot API based channel (uses requests)."""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

import requests

from .base import ChannelInterface

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramChannel(ChannelInterface):
    """Channel for conversing with HermitAgent via a Telegram Bot.

    Environment variables:
        TELEGRAM_BOT_TOKEN   — bot token (issued by BotFather)
        TELEGRAM_CHAT_ID     — chat_id to send and receive messages

    Usage example:
        channel = TelegramChannel()
        tools = create_default_tools(
            cwd="/path/to/repo",
            question_queue=channel.question_queue,
            reply_queue=channel.reply_queue,
        )
        agent = AgentLoop(
            llm=llm,
            tools=tools,
            cwd="/path/to/repo",
            permission_mode=PermissionMode.YOLO,
            on_tool_result=channel.make_progress_hook(),
        )
        channel.start()
        try:
            result = agent.run("/feature-develop 4086")
            channel.send(f"Completed:\n{result}")
        finally:
            channel.stop()
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | int | None = None,
    ) -> None:
        super().__init__()
        self._token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID", ""))
        if not self._token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set.")
        if not self._chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is not set.")
        self._offset: int = 0  # getUpdates offset (ack tracking)

    # ── Telegram API helpers ────────────────────────────────────────────────────

    def _api_url(self, method: str) -> str:
        return _API_BASE.format(token=self._token, method=method)

    def _post(self, method: str, payload: dict) -> dict[str, Any]:
        """Telegram API POST request."""
        url = self._api_url(method)
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            raise RuntimeError(f"Telegram API error [{e.response.status_code if e.response is not None else '?'}]: {body}") from e

    def _get_updates(self, timeout: int = 30) -> list[dict]:
        """Receive updates via long polling."""
        url = self._api_url("getUpdates")
        params = urllib.parse.urlencode(
            {"offset": self._offset, "timeout": timeout, "allowed_updates": '["message"]'}
        )
        try:
            resp = requests.get(f"{url}?{params}", timeout=timeout + 5)
            resp.raise_for_status()
            return resp.json().get("result", [])
        except Exception:
            return []

    def _send_message(self, text: str, parse_mode: str = "HTML") -> dict:
        """Send a message to the chat."""
        # Telegram message maximum 4096 characters
        if len(text) > 4096:
            text = text[:4093] + "..."
        return self._post(
            "sendMessage",
            {"chat_id": self._chat_id, "text": text, "parse_mode": parse_mode},
        )

    def _edit_message(self, message_id: int, text: str) -> None:
        """Edit an existing message (for progress updates)."""
        if len(text) > 4096:
            text = text[:4093] + "..."
        try:
            self._post(
                "editMessageText",
                {
                    "chat_id": self._chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
        except Exception:
            pass  # continue even if edit fails

    # ── ChannelInterface implementation ────────────────────────────────────────────────

    def send(self, message: str) -> None:
        """Send progress/results as a Telegram message."""
        try:
            self._send_message(f"<b>[HermitAgent]</b> {message}")
        except Exception as e:
            # Telegram send failure must not affect agent execution
            import sys
            print(f"[TelegramChannel] send failed: {e}", file=sys.stderr)

    def _present_question(self, question: str, options: list[str]) -> str:
        """Send one question via Telegram and wait for one reply."""
        lines = ["<b>[HermitAgent question]</b>", "", question]
        if options:
            lines.append("")
            for i, opt in enumerate(options, 1):
                lines.append(f"  {i}. {opt}")
        lines.append("")
        lines.append("<i>Please enter your answer.</i>")
        question_text = "\n".join(lines)

        try:
            self._send_message(question_text)
        except Exception as e:
            import sys
            print(f"[TelegramChannel] Failed to send question: {e}", file=sys.stderr)
            return "skip"

        return self._wait_for_reply()

    def _wait_for_reply(self) -> str:
        """Long-poll Telegram until a user message arrives."""
        while not self._stop_event.is_set():
            updates = self._get_updates(timeout=20)
            for update in updates:
                update_id: int = update["update_id"]
                self._offset = update_id + 1  # ack

                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text: str = msg.get("text", "").strip()

                # only process messages from the specified chat_id
                if chat_id != self._chat_id:
                    continue

                if text:
                    return text

        return "skip"  # Default value when stop_event is set
