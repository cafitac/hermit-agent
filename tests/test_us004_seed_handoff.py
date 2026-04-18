"""US-004: seed_handoff / auto_wrap parameter wiring tests.

RED phase: these tests will fail until implementation is complete.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# 1. AgentLoop accepts seed_handoff / auto_wrap params and stores them
# ---------------------------------------------------------------------------

def test_agentloop_accepts_seed_handoff_false(tmp_path):
    """AgentLoop(seed_handoff=False) must not raise and must store the value."""
    from unittest.mock import MagicMock
    from hermit_agent.loop import AgentLoop

    fake_llm = MagicMock()
    agent = AgentLoop(llm=fake_llm, tools=[], cwd=str(tmp_path), seed_handoff=False)
    assert agent.seed_handoff is False


def test_agentloop_accepts_auto_wrap_false(tmp_path):
    """AgentLoop(auto_wrap=False) must not raise and must store the value."""
    from unittest.mock import MagicMock
    from hermit_agent.loop import AgentLoop

    fake_llm = MagicMock()
    agent = AgentLoop(llm=fake_llm, tools=[], cwd=str(tmp_path), auto_wrap=False)
    assert agent.auto_wrap is False


def test_agentloop_defaults_true(tmp_path):
    """AgentLoop() defaults: seed_handoff=True, auto_wrap=True."""
    from unittest.mock import MagicMock
    from hermit_agent.loop import AgentLoop

    fake_llm = MagicMock()
    agent = AgentLoop(llm=fake_llm, tools=[], cwd=str(tmp_path))
    assert agent.seed_handoff is True
    assert agent.auto_wrap is True


# ---------------------------------------------------------------------------
# 2. config.DEFAULTS has the new keys
# ---------------------------------------------------------------------------

def test_config_defaults_has_seed_handoff():
    from hermit_agent.config import DEFAULTS
    assert "seed_handoff" in DEFAULTS
    assert DEFAULTS["seed_handoff"] is True


def test_config_defaults_has_auto_wrap():
    from hermit_agent.config import DEFAULTS
    assert "auto_wrap" in DEFAULTS
    assert DEFAULTS["auto_wrap"] is True


# ---------------------------------------------------------------------------
# 3. _ENV_MAP has the new env var mappings
# ---------------------------------------------------------------------------

def test_env_map_has_seed_handoff():
    from hermit_agent.config import _ENV_MAP
    assert "HERMIT_SEED_HANDOFF" in _ENV_MAP
    assert _ENV_MAP["HERMIT_SEED_HANDOFF"] == "seed_handoff"


def test_env_map_has_auto_wrap():
    from hermit_agent.config import _ENV_MAP
    assert "HERMIT_AUTO_WRAP" in _ENV_MAP
    assert _ENV_MAP["HERMIT_AUTO_WRAP"] == "auto_wrap"


# ---------------------------------------------------------------------------
# 4. load_settings() coerces env var strings to bool
# ---------------------------------------------------------------------------

def test_load_settings_coerces_seed_handoff_false(monkeypatch):
    monkeypatch.setenv("HERMIT_SEED_HANDOFF", "0")
    from hermit_agent import config
    settings = config.load_settings()
    assert settings["seed_handoff"] is False


def test_load_settings_coerces_seed_handoff_true(monkeypatch):
    monkeypatch.setenv("HERMIT_SEED_HANDOFF", "1")
    from hermit_agent import config
    settings = config.load_settings()
    assert settings["seed_handoff"] is True


def test_load_settings_coerces_auto_wrap_false(monkeypatch):
    monkeypatch.setenv("HERMIT_AUTO_WRAP", "false")
    from hermit_agent import config
    settings = config.load_settings()
    assert settings["auto_wrap"] is False


def test_load_settings_no_env_returns_default_bool(monkeypatch):
    monkeypatch.delenv("HERMIT_SEED_HANDOFF", raising=False)
    monkeypatch.delenv("HERMIT_AUTO_WRAP", raising=False)
    from hermit_agent import config
    settings = config.load_settings()
    assert isinstance(settings["seed_handoff"], bool)
    assert isinstance(settings["auto_wrap"], bool)
