"""Tests for CLI argument defaults in hermit_agent.__main__."""
import os

import pytest

from hermit_agent.__main__ import parse_args


class TestDefaultBaseUrl:
    def test_default_base_url_is_gateway(self):
        """--base-url default must point to the local Hermit gateway, not Ollama."""
        ns = parse_args([])
        assert ns.base_url == "http://localhost:8765/v1"

    def test_custom_base_url_overrides_default(self):
        ns = parse_args(["--base-url", "http://x"])
        assert ns.base_url == "http://x"


class TestDefaultApiKey:
    def test_default_api_key_is_none_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("HERMIT_API_KEY", raising=False)
        ns = parse_args([])
        assert ns.api_key is None

    def test_default_api_key_reads_env(self, monkeypatch):
        monkeypatch.setenv("HERMIT_API_KEY", "tok-test-123")
        ns = parse_args([])
        assert ns.api_key == "tok-test-123"
