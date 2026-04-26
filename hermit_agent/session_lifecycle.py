"""Session lifecycle helpers — event logging and session archiving."""
from __future__ import annotations

import logging
import os
from typing import Any

_logger = logging.getLogger(__name__)


class SessionLifecycle:
    """Handles session event logging and archiving for an AgentLoop session."""

    def __init__(self, llm: Any, session_id: str) -> None:
        self._llm = llm
        self._session_id = session_id

    @property
    def _session_logger(self) -> Any | None:
        return getattr(self._llm, "session_logger", None)

    def log_assistant_text(self, text: str) -> None:
        logger = self._session_logger
        if logger is not None and text:
            try:
                logger.log_assistant_text(text)
            except Exception as exc:
                _logger.debug("log_assistant_text: %s", exc)

    def log_tool_use(self, tc: Any) -> None:
        logger = self._session_logger
        if logger is None:
            return
        try:
            logger.log_tool_use(tc.id, tc.name, tc.arguments)
        except Exception as exc:
            _logger.debug("log_tool_use: %s", exc)

    def log_tool_result(self, tool_use_id: str, result: Any) -> None:
        logger = self._session_logger
        if logger is None:
            return
        try:
            content = result.content if hasattr(result, "content") else str(result)
            is_error = bool(getattr(result, "is_error", False))
            logger.log_tool_result(tool_use_id, content, is_error=is_error)
        except Exception as exc:
            _logger.debug("log_tool_result: %s", exc)

    def log_attachment(self, kind: str, content: str, **extra: Any) -> None:
        logger = self._session_logger
        if logger is None:
            return
        try:
            logger.log_attachment(kind, content, **extra)
        except Exception as exc:
            _logger.debug("log_attachment: %s", exc)

    def log_session_outcome(
        self,
        *,
        model: str,
        last_termination: str | None,
        compact_count: int,
        test_pass_count: int,
        test_fail_count: int,
        loop_reentry_count: int,
    ) -> None:
        self.log_attachment(
            "session_outcome",
            "",
            model=model,
            success=last_termination == "completed",
            termination=last_termination,
            compact_count=compact_count,
            test_pass_count=test_pass_count,
            test_fail_count=test_fail_count,
            loop_reentry_count=loop_reentry_count,
        )

    def archive_session(self) -> None:
        """Copy session JSONL to ~/.hermit/metrics/sessions/."""
        logger = self._session_logger
        if logger is None:
            return
        try:
            import shutil
            metrics_dir = os.path.join(
                os.path.expanduser("~"), ".hermit", "metrics", "sessions"
            )
            os.makedirs(metrics_dir, exist_ok=True)
            dest = os.path.join(metrics_dir, f"{self._session_id}.jsonl")
            shutil.copy2(logger.jsonl_path, dest)
        except Exception as exc:
            _logger.debug("archive_session failed: %s", exc)
