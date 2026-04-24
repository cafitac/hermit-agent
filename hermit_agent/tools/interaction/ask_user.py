"""User interaction tool (AskUserQuestionTool)."""

from __future__ import annotations

from queue import Queue
from typing import Any, Callable, Optional

from ..base import Tool, ToolResult


class AskUserQuestionTool(Tool):
    """Claude Code's AskUserQuestion tool implementation.

    Two modes:
    - Normal mode (question_queue=None): returns question text and the LLM stops
    - MCP bidirectional mode (question_queue injected): puts the question into question_queue
      and receives the actual answer from reply_queue, returning it as ToolResult
    """

    name = "ask_user_question"
    description = (
        "Ask the user a question and wait for their response. "
        "CRITICAL INSTRUCTIONS AFTER CALLING THIS TOOL:\n"
        "1. Output the question text VERBATIM in your response so the user can read it.\n"
        "2. Do NOT call any other tools.\n"
        "3. Do NOT proceed to the next step.\n"
        "4. STOP and wait — the user's next message is their answer."
    )
    is_read_only = True

    def __init__(
        self,
        question_queue: Optional[Queue[Any]] = None,
        reply_queue: Optional[Queue[Any]] = None,
        notify_fn: Callable[[str, list[str]], None] | None = None,
        notify_running_fn: Callable[[], None] | None = None,
    ) -> None:
        self._q_out = question_queue  # MCP: put questions here
        self._q_in = reply_queue      # MCP: get answers here
        self._notify_fn = notify_fn   # hermit-channel HTTP notification callback
        self._notify_running_fn = notify_running_fn  # terminate retry loop immediately after consuming reply

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of answer choices to present",
                },
            },
            "required": ["question"],
        }

    def execute(self, input: dict[str, Any]) -> ToolResult:
        import json as _json
        question = input.get("question", "")
        options = input.get("options", [])
        # Handle cases where the LLM passes options as a JSON string (e.g. "[\"start\", \"skip\"]")
        if isinstance(options, str):
            try:
                options = _json.loads(options)
            except (_json.JSONDecodeError, ValueError):
                options = [options]

        if self._q_out is not None:
            # MCP bidirectional mode: put question into queue and wait for actual answer
            self._q_out.put({"question": question, "options": options})
            if self._notify_fn:
                try:
                    self._notify_fn(question, options)
                except Exception:
                    pass
            if self._q_in is None:
                return ToolResult(content="[ask_user_question misconfigured: reply queue missing]", is_error=True)
            reply = self._q_in.get()  # blocks until reply_task is called
            # Running notification right after consuming reply → stops server.ts retry loop immediately
            if self._notify_running_fn:
                try:
                    self._notify_running_fn()
                except Exception:
                    pass
            if reply == "__CANCELLED__":
                return ToolResult(content="[Task cancelled.]", is_error=True)
            return ToolResult(content=reply)

        # Normal mode: return question text → LLM outputs it and stops
        parts = [question]
        if options:
            parts.append("")
            for i, opt in enumerate(options, 1):
                parts.append(f"  {i}. {opt}")

        parts.append(
            "\n[Wait for the user\'s response. Do not proceed to the next step until they respond.]"
        )
        return ToolResult(content="\n".join(parts))


__all__ = ['AskUserQuestionTool']
