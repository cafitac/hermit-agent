from __future__ import annotations

from typing import Any
from ..version import VERSION

SERVER_INFO = {"name": "hermit_agent", "version": VERSION}
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_MODEL = "qwen3-coder:30b"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_task",
        "description": (
            "Run a coding task using a local LLM (default: qwen3-coder:30b).\n"
            "If background=true, immediately returns {status:'running', task_id} and runs in the background.\n"
            "Check completion with check_task(task_id).\n"
            "Return values:\n"
            '  {status:"running", task_id} — running in background (when background=true).\n'
            '  {status:"waiting", task_id, question, options} — HermitAgent is asking a question. '
            "Reply with reply_task(task_id, message).\n"
            '  {status:"done", result} — task completed.'
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task description to execute"},
                "cwd": {"type": "string", "description": "Absolute path of working directory"},
                "model": {"type": "string", "description": f"Model to use (default: {DEFAULT_MODEL})"},
                "max_turns": {"type": "integer", "description": "Maximum number of turns (default: 200)"},
                "background": {"type": "boolean", "description": "If true, return task_id immediately and run in background (default: false)"},
            },
            "required": ["task", "cwd"],
        },
    },
    {
        "name": "reply_task",
        "description": (
            "Send a reply to HermitAgent when run_task returned {status:\"waiting\"}.\n"
            "Return format is the same as run_task (waiting or done)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id returned by run_task"},
                "message": {"type": "string", "description": "Reply to send to HermitAgent"},
            },
            "required": ["task_id", "message"],
        },
    },
    {
        "name": "check_task",
        "description": (
            "Check the current status of a background task (use after run_task with background=true).\n"
            "Return values:\n"
            '  {status:"running"} — still running.\n'
            '  {status:"waiting", question, options} — user input required.\n'
            '  {status:"done", result} — completed.\n'
            '  {status:"not_found"} — task_id not found (already completed and removed).\n'
            "Use full=true to retrieve the complete result without truncation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id returned by run_task"},
                "full": {
                    "type": "boolean",
                    "description": "If true, return the complete result without truncation (default: false).",
                    "default": False,
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "cancel_task",
        "description": "Cancel a running task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id to cancel"},
            },
            "required": ["task_id"],
        },
    },
]
