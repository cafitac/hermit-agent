from __future__ import annotations

import json

from hermit_agent.launcher_health import gateway_identity_ok, main


class _DummyResponse:
    def __init__(self, payload: dict[str, object], status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_gateway_identity_ok_true(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.launcher_health.urlopen",
        lambda url, timeout=1.0: _DummyResponse({"service": "hermit_agent-gateway"}),
    )

    assert gateway_identity_ok("http://127.0.0.1:8765") is True


def test_gateway_identity_ok_false_for_wrong_service(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.launcher_health.urlopen",
        lambda url, timeout=1.0: _DummyResponse({"service": "something-else"}),
    )

    assert gateway_identity_ok("http://127.0.0.1:8765") is False


def test_main_returns_nonzero_without_url(capsys):
    assert main([]) == 2
    assert "Usage:" in capsys.readouterr().err
