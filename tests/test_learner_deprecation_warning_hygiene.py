from __future__ import annotations

import subprocess
import sys


def test_legacy_learner_tests_assert_their_deprecation_warnings() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_learner_auto.py",
            "tests/test_learner_project_local.py",
            "tests/test_learner_verification.py",
            "-q",
            "-W",
            "always::DeprecationWarning",
        ],
        cwd=".",
        text=True,
        capture_output=True,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "hermit_agent.learner.Learner is deprecated" not in output
    assert "warnings summary" not in output
