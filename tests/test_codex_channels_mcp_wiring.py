"""Tests for codex-channels sink wiring in MCP channel pipeline.

Verifies that the sink is part of the default composite but gracefully
degrades when not enabled or when the server is unreachable.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from hermit_agent.interactive_prompts import InteractivePrompt, create_interactive_prompt


@dataclass
class _FakeSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4317


def _make_prompt(task_id: str = "wiring-test-001") -> InteractivePrompt:
    return create_interactive_prompt(
        task_id=task_id,
        question="Allow?",
        options=["yes", "no"],
        prompt_kind="permission_ask",
    )


class TestCodexChannelsSinkInDefaultComposite:
    """Verify the sink is included in the default composite but inactive by default."""

    def test_default_sink_includes_codex_channels(self):
        from hermit_agent.mcp_channel import _default_interactive_sink

        # The default composite should have at least 2 sinks: claude + codex_channels
        assert len(_default_interactive_sink._sinks) >= 2
        sink_types = [type(s).__name__ for s in _default_interactive_sink._sinks]
        assert "CodexChannelsInteractiveSink" in sink_types

    def test_notify_does_not_raise_with_default_disabled_settings(self, monkeypatch):
        """When codex_channels.enabled=False (default), notify must not raise."""
        from hermit_agent.mcp_channel import _default_interactive_sink

        # Default settings have enabled=False → health check short-circuits
        prompt = _make_prompt()
        # This should not raise even without a running server
        _default_interactive_sink.notify(prompt)

    def test_notify_graceful_when_enabled_but_server_down(self, monkeypatch):
        """When enabled=True but server is unreachable, notify must not raise."""
        from hermit_agent.mcp_channel import _codex_channels_sink

        def _raise(*a, **kw):
            raise OSError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)

        # Force settings to enabled=True
        monkeypatch.setattr(
            _codex_channels_sink, "is_available", lambda *, settings: True
        )
        # But maybe_start returns None (session start fails)
        monkeypatch.setattr(
            "hermit_agent.interactive_sinks.codex_channels.maybe_start_codex_channels_wait_session",
            lambda *a, **kw: None,
        )

        prompt = _make_prompt()
        _codex_channels_sink.notify(prompt)
        assert prompt.task_id not in _codex_channels_sink.sessions


class TestCodexChannelsSinkExcludedForAppServerSessions:
    """When a session-level app server sink is active, codex-channels is excluded."""

    def test_current_interactive_sink_excludes_codex_channels_for_session(
        self, monkeypatch
    ):
        from hermit_agent.mcp_channel import _current_interactive_sink

        # Simulate a session being active (returns a non-None session sink)
        mock_sink = MagicMock()
        monkeypatch.setattr(
            "hermit_agent.mcp_channel._build_session_app_server_sink",
            lambda: mock_sink,
        )

        sink = _current_interactive_sink()
        sink_types = [type(s).__name__ for s in sink._sinks]
        assert "CodexChannelsInteractiveSink" not in sink_types
