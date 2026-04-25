"""Session log — records agent events as JSONL + text.

Structure (see §25):
  {cwd}/.hermit/session.log          — human-readable text log (backward-compatible)
  {cwd}/.hermit/session.jsonl        — CC format-compatible JSONL (record per line)
  {cwd}/.hermit/subagents/
      agent-<id>.jsonl                — sub-agent dedicated JSONL
      agent-<id>.meta.json            — sub-agent metadata

Record types: user / assistant / tool_result / attachment / permission-mode
"""

from __future__ import annotations

import json
import os
import threading
import time

from ..log_retention import append_jsonl_record


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S") + time.strftime("%z")


def _hhmmss() -> str:
    return time.strftime("%H:%M:%S")


class SessionLogger:
    """Logger that records agent events as JSONL (CC .jsonl format compatible).

    session.jsonl — all events are stored as record-per-line.
    Text log (session.log) is deprecated — replaced by JSONL parsing.

    Thread-safe (Lock-protected).
    """

    def __init__(self, session_dir: str) -> None:
        self.session_dir = session_dir
        self.session_id = os.path.basename(session_dir)
        self.jsonl_path = os.path.join(session_dir, "events.jsonl")
        self.subagents_dir = os.path.join(session_dir, "subagents")
        self._lock = threading.Lock()

    # ── Low-level write ────────────────────────────

    def _write_jsonl(self, record: dict) -> None:
        try:
            with self._lock:
                append_jsonl_record(
                    self.jsonl_path,
                    json.dumps(record, ensure_ascii=False) + "\n",
                )
        except Exception:
            pass

    # ── Legacy tag-based API ──────────────────
    # Used by llm_client for [LLM_CALL_SLOW] / [LLM_CALL_TIMEOUT] etc.
    # Saved as an attachment record inside the JSONL.

    def log(self, tag: str, content: str) -> None:
        self._write_jsonl({
            "type": "attachment",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "kind": tag.lower(),
            "content": content,
        })

    # ── JSONL-only API ────────────────────────

    def log_user(self, text: str) -> None:
        self._write_jsonl({
            "type": "user",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "content": text,
        })

    def log_assistant_text(self, text: str) -> None:
        """LLM text content — summary at turn end, etc."""
        if not text:
            return
        self._write_jsonl({
            "type": "assistant",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "content": [{"type": "text", "text": text}],
        })

    def log_tool_use(self, tool_use_id: str, name: str, input: dict) -> None:
        # Text logging to session.log is handled by bridge's on_send() (to avoid duplication).
        # Here we only write the JSONL record.
        self._write_jsonl({
            "type": "assistant",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "content": [{
                "type": "tool_use",
                "id": tool_use_id,
                "name": name,
                "input": input,
            }],
        })

    def log_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> None:
        # Text logging to session.log is handled by bridge's on_send() (to avoid duplication).
        self._write_jsonl({
            "type": "tool_result",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        })

    def log_attachment(self, kind: str, content: str, **extra) -> None:
        record = {
            "type": "attachment",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "kind": kind,
            "content": content,
        }
        record.update(extra)
        self._write_jsonl(record)

    def log_permission_mode(self, mode: str) -> None:
        self._write_jsonl({
            "type": "permission-mode",
            "timestamp": _now_iso(),
            "session_id": self.session_id,
            "mode": mode,
        })

    # ── bridge._send() dispatcher ────────────────

    def on_send(self, msg: dict) -> None:
        """Called from _send() — records events emitted by the bridge into JSONL.

        tool_use/tool_result are already written to JSONL by loop.py via
        `_log_tool_use`/`_log_tool_result`, so they are skipped here (to avoid
        duplication). Only text/error/done are saved as attachment or assistant_text.
        """
        t = msg.get("type", "")
        if t == "text":
            content = str(msg.get("content", ""))
            if content:
                self.log_assistant_text(content)
        elif t == "error":
            self.log_attachment("error", str(msg.get("message", "")))
        elif t == "done":
            self.log_attachment("done", "")

    def on_user_input(self, text: str) -> None:
        self.log_user(text[:2000])

    # ── Sub-agent ─────────────────────────────────

    def create_subagent_logger(
        self,
        agent_id: str,
        agent_type: str,
        description: str,
    ) -> "SubAgentLogger":
        os.makedirs(self.subagents_dir, exist_ok=True)
        sub = SubAgentLogger(
            subagents_dir=self.subagents_dir,
            agent_id=agent_id,
            agent_type=agent_type,
            description=description,
            parent_session_id=self.session_id,
        )
        # Record dispatch attachment in the parent log
        self.log_attachment(
            kind="subagent_dispatch",
            content=description,
            agent_id=agent_id,
            agent_type=agent_type,
        )
        return sub


class SubAgentLogger:
    """Dedicated JSONL logger for sub-agents. Records lifecycle in meta.json."""

    def __init__(
        self,
        subagents_dir: str,
        agent_id: str,
        agent_type: str,
        description: str,
        parent_session_id: str,
    ) -> None:
        self.agent_id = agent_id
        self.jsonl_path = os.path.join(subagents_dir, f"agent-{agent_id}.jsonl")
        self.meta_path = os.path.join(subagents_dir, f"agent-{agent_id}.meta.json")
        self._lock = threading.Lock()
        self._meta = {
            "agent_id": agent_id,
            "agentType": agent_type,
            "description": description,
            "parent_session_id": parent_session_id,
            "started_at": _now_iso(),
        }
        with open(self.jsonl_path, "w", encoding="utf-8"):
            pass  # truncate to empty; each subagent gets a unique agent_id
        self._write_meta()

    def _write_meta(self) -> None:
        try:
            with self._lock:
                with open(self.meta_path, "w", encoding="utf-8") as f:
                    json.dump(self._meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _write_jsonl(self, record: dict) -> None:
        try:
            with self._lock:
                append_jsonl_record(
                    self.jsonl_path,
                    json.dumps(record, ensure_ascii=False) + "\n",
                )
        except Exception:
            pass

    def log_user(self, text: str) -> None:
        self._write_jsonl({"type": "user", "timestamp": _now_iso(), "content": text})

    def log_assistant_text(self, text: str) -> None:
        if not text:
            return
        self._write_jsonl({
            "type": "assistant",
            "timestamp": _now_iso(),
            "content": [{"type": "text", "text": text}],
        })

    def log_tool_use(self, tool_use_id: str, name: str, input: dict) -> None:
        self._write_jsonl({
            "type": "assistant",
            "timestamp": _now_iso(),
            "content": [{"type": "tool_use", "id": tool_use_id, "name": name, "input": input}],
        })

    def log_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> None:
        self._write_jsonl({
            "type": "tool_result",
            "timestamp": _now_iso(),
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        })

    def finish(self, result_summary: str = "") -> None:
        self._meta["ended_at"] = _now_iso()
        if result_summary:
            self._meta["result_summary"] = result_summary
        self._write_meta()
