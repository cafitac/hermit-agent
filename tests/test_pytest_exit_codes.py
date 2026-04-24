"""G33 — Verify distinct messages by pytest exit code."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.tools import RunTestsTool


def _format(returncode: int, output: str = "", test_path: str = "") -> tuple[str, bool]:
    """Direct call to RunTestsTool._format_pytest_output."""
    tool = RunTestsTool(cwd=".")
    return tool._format_pytest_output(returncode, output, test_path)


def test_exit_0_is_passed():
    content, is_error = _format(0, "===== 3 passed in 0.10s =====")
    assert not is_error
    assert "PASSED" in content


def test_exit_1_is_test_failed_with_traceback():
    output = "test_x.py::test_fail FAILED\nE   AssertionError: foo\n===== 1 failed in 0.10s ====="
    content, is_error = _format(1, output)
    assert is_error
    assert "TEST FAILED" in content
    assert "AssertionError" in content  # Includes traceback


def test_exit_2_is_interrupted():
    content, is_error = _format(2, "!!! KeyboardInterrupt !!!")
    assert is_error
    assert "INTERRUPTED" in content


def test_exit_5_is_no_tests_collected_with_hint():
    content, is_error = _format(5, "no tests ran", test_path="tests/missing.py")
    assert is_error
    assert "NO TESTS COLLECTED" in content
    # Hint that path/pattern verification is needed
    assert "path" in content.lower() or "pattern" in content.lower()


def test_other_exit_code_reports_code_number():
    content, is_error = _format(4, "usage error")
    assert is_error
    assert "exit 4" in content or "exit code 4" in content
