"""Tests for hermit_agent.gateway.routing.resolve_platform."""
import pytest

from hermit_agent.gateway.routing import UnknownPlatform, resolve_platform


class TestOllamaNameTag:
    def test_qwen3_coder_returns_local(self):
        assert resolve_platform("qwen3-coder:30b") == "local"

    def test_llama3_8b_returns_local(self):
        assert resolve_platform("llama3:8b") == "local"


class TestGlmPrefix:
    def test_glm_5_1_returns_zai(self):
        assert resolve_platform("glm-5.1") == "z.ai"

    def test_glm_4_7_returns_zai(self):
        assert resolve_platform("glm-4.7") == "z.ai"

    def test_glm_5_1_air_returns_zai(self):
        assert resolve_platform("glm-5.1-air") == "z.ai"


class TestUnknownModel:
    def test_gpt4_raises(self):
        with pytest.raises(UnknownPlatform) as exc_info:
            resolve_platform("gpt-4")
        assert exc_info.value.model == "gpt-4"

    def test_claude_raises(self):
        with pytest.raises(UnknownPlatform) as exc_info:
            resolve_platform("claude-3-5-sonnet")
        assert exc_info.value.model == "claude-3-5-sonnet"


class TestEmptyString:
    def test_empty_string_raises(self):
        with pytest.raises(UnknownPlatform) as exc_info:
            resolve_platform("")
        assert exc_info.value.model == ""


class TestColonOnly:
    def test_colon_only_returns_local(self):
        # ":latest" contains ":" so the colon-presence rule fires first.
        # This is intentional: the rule matches the ollama name:tag pattern
        # structurally (presence of ":"), not semantically.
        assert resolve_platform(":latest") == "local"
