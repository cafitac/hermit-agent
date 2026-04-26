"""Loop-guard state and logic — edit-loop detection, test failure tracking."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools import ToolResult


class LoopGuards:
    """Tracks guard state for speculative-edit loop detection and test failure hints.

    Extracted from AgentLoop to separate state from orchestration logic.
    """

    def __init__(self, cwd: str) -> None:
        self._cwd = cwd
        # Edit loop guard state (G26 / G48)
        self._last_edit_path: str | None = None
        self._consecutive_same_file_edits: int = 0
        self._read_paths_since_last_edit: set[str] = set()
        self.consecutive_test_failures: int = 0
        self._last_test_hint_count: int = 0
        # Outcome metrics
        self.total_test_passes: int = 0
        self.total_test_failures: int = 0

    def _abs_path(self, path: str) -> str:
        return os.path.abspath(os.path.join(self._cwd, path))

    def check_edit_loop(self, name: str, arguments: dict) -> "ToolResult | None":
        """Return a blocking ToolResult if a speculative edit loop is detected (G26/G48).

        Returns None to allow the edit, or an error ToolResult to block it.
        """
        from .tools import ToolResult

        if name != "edit_file":
            return None
        path = arguments.get("path", "")
        if not path:
            return None
        abs_path = self._abs_path(path)
        if (
            self._last_edit_path == abs_path
            and self._consecutive_same_file_edits >= 2
            and abs_path not in self._read_paths_since_last_edit
            and self.consecutive_test_failures > 0  # G48: only block after test failures
        ):
            return ToolResult(
                content=(
                    f"[Loop guard] Attempted to edit the same file '{path}' 3 times in a row without a read_file. "
                    "Blocked to prevent speculative repeat edits.\n"
                    "Do these steps first:\n"
                    "1. Re-read the current file with read_file\n"
                    "2. Re-check the failing test's traceback via grep/read_file\n"
                    "3. Only after identifying the root cause, attempt a precise edit_file"
                ),
                is_error=True,
            )
        return None

    def track(self, name: str, arguments: dict, result: "ToolResult") -> None:
        """Update guard state after a tool call completes."""
        if name == "read_file":
            p = arguments.get("path", "")
            if p:
                self._read_paths_since_last_edit.add(self._abs_path(p))
            return

        if name == "edit_file" and not result.is_error:
            p = arguments.get("path", "")
            abs_p = self._abs_path(p)
            if self._last_edit_path == abs_p:
                self._consecutive_same_file_edits += 1
            else:
                self._last_edit_path = abs_p
                self._consecutive_same_file_edits = 1
            self._read_paths_since_last_edit.discard(abs_p)
            return

        if name == "run_tests":
            if result.is_error:
                self.consecutive_test_failures += 1
                self.total_test_failures += 1
            else:
                self.consecutive_test_failures = 0
                self._last_test_hint_count = 0
                self.total_test_passes += 1
            return
