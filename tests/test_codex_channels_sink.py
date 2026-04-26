"""Tests for CodexChannelsInteractiveSink health check and graceful degradation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from hermit_agent.interactive_prompts import InteractivePrompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4317


def _make_prompt(task_id: str = "t-001") -> InteractivePrompt:
    return InteractivePrompt(
        task_id=task_id,
        question="Proceed?",
        options=("yes", "no"),
    )


def _make_sink(
    *,
    enabled: bool = True,
    settings: FakeSettings | None = None,
    session_factory: Any = None,
    reply_callback: Any = None,
):
    from hermit_agent.interactive_sinks.codex_channels import CodexChannelsInteractiveSink

    _settings = settings or FakeSettings(enabled=enabled)

    def settings_loader(_prompt):
        return _settings

    return CodexChannelsInteractiveSink(
        settings_loader=settings_loader,
        session_factory=session_factory or (lambda **kw: MagicMock()),
        interaction_builder=lambda p: {"id": p.task_id},
        reply_callback=reply_callback or (lambda p, a: None),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_returns_false_when_not_enabled(self):
        sink = _make_sink(enabled=False)
        assert sink.is_available(settings=FakeSettings(enabled=False)) is False

    def test_returns_false_on_connection_error(self, monkeypatch):
        def _raise(*a, **kw):
            raise OSError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        sink = _make_sink(enabled=True)
        assert sink.is_available(settings=FakeSettings(enabled=True)) is False

    def test_returns_true_on_200(self, monkeypatch):
        class MockResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: MockResp())
        sink = _make_sink(enabled=True)
        assert sink.is_available(settings=FakeSettings(enabled=True)) is True

    def test_returns_false_on_500(self, monkeypatch):
        class MockResp:
            status = 500

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: MockResp())
        sink = _make_sink(enabled=True)
        assert sink.is_available(settings=FakeSettings(enabled=True)) is False


class TestGracefulDegradation:
    def test_notify_does_nothing_when_not_enabled(self):
        sink = _make_sink(enabled=False)
        prompt = _make_prompt()
        sink.notify(prompt)
        # No sessions created, no exception
        assert sink.sessions == {}

    def test_notify_does_nothing_when_server_down(self, monkeypatch):
        def _raise(*a, **kw):
            raise OSError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", _raise)
        sink = _make_sink(enabled=True)
        prompt = _make_prompt()
        sink.notify(prompt)
        assert sink.sessions == {}

    def test_notify_creates_session_when_available(self, monkeypatch):
        class MockResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: MockResp())

        mock_session = MagicMock()
        mock_thread = MagicMock()  # prevent real background thread
        sink = _make_sink(enabled=True, session_factory=lambda **kw: mock_session)
        sink._thread_factory = MagicMock(return_value=mock_thread)
        prompt = _make_prompt()
        sink.notify(prompt)
        assert prompt.task_id in sink.sessions
