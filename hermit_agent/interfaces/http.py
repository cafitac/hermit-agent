"""HTTPChannel — channel that integrates with the hermit-channel server.

Flow:
  HermitAgent → POST /notify           → hermit-channel → Claude Code (MCP)
  HermitAgent ← GET  /task/:id/answer  ← hermit-channel ← Claude Code (POST /task/:id/answer)
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from .base import ChannelInterface

_DEFAULT_URL = "http://127.0.0.1:8789"


class HTTPChannel(ChannelInterface):
    """Channel that communicates with Claude Code via the hermit-channel HTTP server.

    Environment variables:
        HERMIT_CHANNEL_URL   — hermit-channel server address (default: http://127.0.0.1:8789)
        HERMIT_TASK_ID       — current task ID (for task-specific answer routing)

    Usage example:
        channel = HTTPChannel(task_id="abc123")
        tools = create_default_tools(
            cwd="/path/to/repo",
            question_queue=channel.question_queue,
            reply_queue=channel.reply_queue,
        )
        agent = AgentLoop(
            llm=llm, tools=tools, cwd="/path/to/repo",
            permission_mode=PermissionMode.YOLO,
            on_tool_result=channel.make_progress_hook(),
        )
        channel.start()
        try:
            result = agent.run("/feature-develop 4086")
            channel.notify("done", message=result)
        finally:
            channel.stop()
    """

    def __init__(
        self,
        task_id: str | None = None,
        channel_url: str | None = None,
    ) -> None:
        super().__init__()
        self._task_id = task_id or os.environ.get("HERMIT_TASK_ID", "unknown")
        self._url = (channel_url or os.environ.get("HERMIT_CHANNEL_URL", _DEFAULT_URL)).rstrip("/")

    # ── HTTP helpers ────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._url}{path}"
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            if not resp.content:
                return {}
            try:
                return resp.json()
            except json.JSONDecodeError:
                return {"raw": resp.content.decode(errors="replace")}
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            raise RuntimeError(f"HTTPChannel POST error [{e.response.status_code if e.response is not None else '?'}]: {body}") from e

    def _get(self, path: str, timeout: int = 5) -> tuple[int, bytes]:
        url = f"{self._url}{path}"
        try:
            resp = requests.get(url, timeout=timeout)
            return resp.status_code, resp.content
        except requests.HTTPError as e:
            return e.response.status_code, e.response.content

    # ── external notifications ────────────────────────────────────────────────────────────

    def notify(
        self,
        type: str,  # noqa: A002
        *,
        question: str | None = None,
        options: list[str] | None = None,
        message: str | None = None,
        step: str | None = None,
    ) -> None:
        """Send an event to the hermit-channel /notify endpoint."""
        payload: dict[str, Any] = {"task_id": self._task_id, "type": type}
        if question is not None:
            payload["question"] = question
        if options is not None:
            payload["options"] = options
        if message is not None:
            payload["message"] = message
        if step is not None:
            payload["step"] = step
        try:
            self._post("/notify", payload)
        except Exception as e:
            import sys
            print(f"[HTTPChannel] notify failed: {e}", file=sys.stderr)

    # ── ChannelInterface implementation ────────────────────────────────────────────────

    def send(self, message: str) -> None:
        """Send progress/results to hermit-channel as a progress event."""
        self.notify("progress", message=message)

    def _present_question(self, question: str, options: list[str]) -> str:
        """Forward one question to Claude Code and poll for one answer."""
        self.notify("waiting", question=question, options=options or None)
        # DEPRECATED: Post stdio-only channel merger, _poll_for_answer() is no longer supported.
        return self._poll_for_answer()

    def _poll_for_answer(self, poll_interval: float = 1.0, max_wait: float = 300.0) -> str:
        """Poll hermit-channel until Claude Code's answer arrives.

        GET /task/:id/answer
          → 200: answer available (body: {"answer": "..."})
          → 204: not yet available
          → other: error handling

        DEPRECATED: Post stdio-only channel merger, there is no server-side /task/:id/answer
        endpoint. HTTP/Docker answer polling is no longer supported. Callers should migrate
        to MCP tool calls (reply_task).
        """
        deadline = time.monotonic() + max_wait
        path = f"/task/{self._task_id}/answer"

        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                status, body = self._get(path, timeout=5)
                if status == 200:
                    data = json.loads(body)
                    return data.get("answer", "skip")
                elif status == 204:
                    time.sleep(poll_interval)
                else:
                    import sys
                    print(f"[HTTPChannel] poll error [{status}]", file=sys.stderr)
                    time.sleep(poll_interval)
            except Exception as e:
                import sys
                print(f"[HTTPChannel] poll exception: {e}", file=sys.stderr)
                time.sleep(poll_interval)

        return "skip"  # Timeout or stop_event
