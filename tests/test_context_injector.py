"""US-002: Unit tests for ContextInjector class."""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_injector(tmp_path: str, max_ctx: int = 32000):
    from hermit_agent.context_injector import ContextInjector

    agent = SimpleNamespace(
        llm=MagicMock(),
        token_totals={"prompt_tokens": 0, "completion_tokens": 0},
        seed_handoff=True,
        cwd=tmp_path,
        context_manager=SimpleNamespace(max_context_tokens=max_ctx),
    )
    return ContextInjector(agent=agent), agent


def test_classify_returns_none_for_need_tools():
    """classify returns None when LLM responds with NEED_TOOLS."""
    with tempfile.TemporaryDirectory() as tmp:
        injector, agent = _make_injector(tmp)
        agent.llm.chat.return_value = SimpleNamespace(
            content="NEED_TOOLS: requires file access",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        result = injector.classify("Write a script to parse JSON")
        assert result is None


def test_classify_returns_response_for_simple_question():
    """classify returns LLM response when it's a simple (non-tool) answer."""
    with tempfile.TemporaryDirectory() as tmp:
        injector, agent = _make_injector(tmp)
        agent.llm.chat.return_value = SimpleNamespace(
            content="The answer is 42.",
            usage={"prompt_tokens": 8, "completion_tokens": 4},
        )
        result = injector.classify("What is 6 times 7?")
        assert result == "The answer is 42."


def test_classify_returns_none_on_llm_exception():
    """classify returns None safely when LLM raises an exception."""
    with tempfile.TemporaryDirectory() as tmp:
        injector, agent = _make_injector(tmp)
        agent.llm.chat.side_effect = RuntimeError("connection refused")
        result = injector.classify("Hello?")
        assert result is None


def test_inject_seed_handoff_no_handoff_dir_returns_unchanged():
    """inject_seed_handoff returns message unchanged when no handoff dir exists."""
    with tempfile.TemporaryDirectory() as tmp:
        injector, _ = _make_injector(tmp)
        msg = "original message"
        result = injector.inject_seed_handoff(msg)
        assert result == msg


def test_inject_seed_handoff_disabled_by_env():
    """inject_seed_handoff returns message unchanged when env var disables it."""
    with tempfile.TemporaryDirectory() as tmp:
        injector, _ = _make_injector(tmp)
        with patch.dict(os.environ, {"HERMIT_SEED_HANDOFF": "0"}):
            result = injector.inject_seed_handoff("hello")
        assert result == "hello"
