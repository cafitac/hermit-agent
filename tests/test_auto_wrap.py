"""Automatically save handoff on HermitAgent shutdown.

Policy (default ON):
- Default on (saves unless explicitly opted out)
- Opt-out: set `HERMIT_AUTO_WRAP` to one of {0, false, no, off}
- Save only when modified_files exist (prevents handoff accumulation in empty sessions)

Red-Green:
1. No maybe_auto_wrap() → Red
2. Implementation → Green
"""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.session_wrap import maybe_auto_wrap


def test_saves_when_env_var_missing():
    """Default ON: saves when HERMIT_AUTO_WRAP is unset."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(os.environ, {}, clear=True):
            path = maybe_auto_wrap(cwd=tmp, session_id="s1", modified_files=["a.py"])
        assert path is not None
        assert path.exists()


def test_no_action_when_no_modified_files():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(os.environ, {"HERMIT_AUTO_WRAP": "1"}):
            path = maybe_auto_wrap(cwd=tmp, session_id="s1", modified_files=[])
        assert path is None


def test_saves_when_enabled_and_has_files():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(os.environ, {"HERMIT_AUTO_WRAP": "1"}):
            path = maybe_auto_wrap(
                cwd=tmp, session_id="sx9", modified_files=["a.py", "b.py"]
            )
        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "a.py" in content
        assert "b.py" in content
        assert "sx9" in path.name


def test_env_var_truthy_values():
    with tempfile.TemporaryDirectory() as tmp:
        for val in ("1", "true", "yes", "on"):
            with patch.dict(os.environ, {"HERMIT_AUTO_WRAP": val}):
                path = maybe_auto_wrap(cwd=tmp, session_id="s", modified_files=["a.py"])
            assert path is not None, f"expected save for value {val!r}"


def test_env_var_falsy_values():
    with tempfile.TemporaryDirectory() as tmp:
        for val in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {"HERMIT_AUTO_WRAP": val}):
                path = maybe_auto_wrap(cwd=tmp, session_id="s", modified_files=["a.py"])
            assert path is None, f"expected no-op for value {val!r}"


def test_saves_when_env_var_empty_string():
    """Empty string is not in _FALSY — treated as default ON."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(os.environ, {"HERMIT_AUTO_WRAP": ""}):
            path = maybe_auto_wrap(cwd=tmp, session_id="s", modified_files=["a.py"])
        assert path is not None
