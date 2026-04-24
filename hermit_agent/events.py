"""AgentEventEmitter — agent → UI event dispatch.

When the agent emits events directly, the bridge converts them to JSON and forwards them to the UI.
When running without a bridge (terminal mode), falls back to print.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable


EventHandler = Callable[[str, dict[str, Any]], None]


class AgentEventEmitter:
    """Agent -> UI event transmission."""

    def __init__(self):
        self._handler: EventHandler | None = None
        self._log_path: str | None = None
        # SessionLogger (G1 wiring). Injected by bridge or tests.
        self.session_logger: Any | None = None

    def set_handler(self, handler: EventHandler) -> None:
        """Handler registered by the bridge."""
        self._handler = handler

    def set_log_file(self, path: str) -> None:
        """Set the activity.log file path — records all tool events."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._log_path = path

    def _write_log(self, event_type: str, data: dict[str, Any]) -> None:
        if not self._log_path:
            return
        try:
            ts = time.strftime("%H:%M:%S")
            if event_type == "tool_use":
                name = data.get("name", "")
                detail = data.get("detail", "")
                line = f"[{ts}] ⏺ {name}({detail})\n"
            elif event_type == "tool_result":
                prefix = "  ⎿  ERR: " if data.get("is_error") else "  ⎿  "
                content = data.get("content", "")
                lines = "\n".join(f"[{ts}] {prefix}{line}" for line in (content or "(empty)").splitlines())
                line = lines + "\n"
            elif event_type == "progress":
                line = f"[{ts}]   {data.get('content', '')}\n"
            else:
                return
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def emit(self, event_type: str, **data: Any) -> None:
        self._write_log(event_type, data)
        if self._handler:
            self._handler(event_type, data)
        else:
            self._print_fallback(event_type, data)

    # ── convenience methods ──────────────────────────

    def progress(self, message: str) -> None:
        """Progress status for Ralph/Autopilot etc."""
        self.emit("progress", content=message)

    def tool_use(self, name: str, detail: str) -> None:
        """Tool invocation start."""
        self.emit("tool_use", name=name, detail=detail)

    def tool_result(self, content: str, is_error: bool = False) -> None:
        """Tool execution result."""
        self.emit("tool_result", content=content, is_error=is_error)

    def warning(self, message: str, severity: str = "low") -> None:
        """Warning notification."""
        self.emit("warning", message=message, severity=severity)

    def text(self, content: str) -> None:
        """General text output."""
        self.emit("streaming", token=content)

    def status_update(self, **fields: Any) -> None:
        """Status update (model, session, etc.)."""
        if "reasoning" in fields:
            reasoning_content = fields.pop("reasoning")
            self.emit("reasoning", content=reasoning_content)
        self.emit("status", **fields)

    def model_changed(self, old: str, new: str) -> None:
        """Model switch."""
        self.emit("model_changed", old_model=old, new_model=new)

    def compact_notice(self, token_count: int, threshold: int, level: int, trigger_point: int | None = None) -> None:
        """Context compaction notification.

        trigger_point: actual compact trigger value (threshold * compact_start_ratio).
                       If None, displayed the same as threshold (backward compatible).
        """
        level_names = {1: "snip", 2: "micro", 3: "collapse", 4: "auto"}
        level_name = level_names.get(level, "auto")
        if trigger_point is not None and trigger_point != threshold:
            msg = f"[Compacting context (level {level}: {level_name}): ~{token_count} tokens > {trigger_point} trigger (threshold {threshold})]"
        else:
            msg = f"[Compacting context (level {level}: {level_name}): ~{token_count} tokens > {threshold} threshold]"
        self.emit("tool_result", content=msg, is_error=False)
        # G1: record compact attachment in session.jsonl
        if self.session_logger is not None:
            try:
                self.session_logger.log_attachment(
                    "compact",
                    msg,
                    token_count=token_count,
                    threshold=threshold,
                    trigger_point=trigger_point,
                    level=level,
                )
            except Exception:
                pass

    # ── terminal fallback ──────────────────────────

    @staticmethod
    def _print_fallback(event_type: str, data: dict[str, Any]) -> None:
        """Print directly to terminal when running without a bridge."""
        if event_type == "progress":
            print(f"\033[35m{data.get('content', '')}\033[0m")
        elif event_type == "tool_use":
            name = data.get("name", "")
            detail = data.get("detail", "")
            print(f"\n\033[36m\033[1m>\033[0m \033[36m{name}\033[0m \033[2m{detail}\033[0m")
        elif event_type == "tool_result":
            content = data.get("content", "")
            is_error = data.get("is_error", False)
            color = "\033[31m" if is_error else "\033[2m"
            print(f"{color}  {content}\033[0m")
        elif event_type == "streaming":
            token = data.get("token", "")
            print(token, end="", flush=True)
        elif event_type == "model_changed":
            old = data.get("old_model", "")
            new = data.get("new_model", "")
            print(f"\033[33m[Model: {old} → {new}]\033[0m")
