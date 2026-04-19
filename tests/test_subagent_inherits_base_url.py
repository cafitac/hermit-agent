"""Verify that SubAgentTool._make_llm inherits base_url from the parent LLM client."""
from unittest.mock import MagicMock, patch

import pytest

from hermit_agent.tools.agent.subagent import SubAgentTool


def _make_parent_llm(base_url: str, model: str = "test-model", api_key: str = "k"):
    """Build a minimal mock that quacks like LLMClientBase."""
    llm = MagicMock()
    llm.base_url = base_url
    llm.model = model
    llm.api_key = api_key
    llm.fallback_model = None
    llm.MODEL_ROUTING = {}
    return llm


def _make_tool(parent_llm) -> SubAgentTool:
    return SubAgentTool(
        llm_client=parent_llm,
        tools_factory=lambda cwd: [],
        cwd=".",
    )


class TestSubagentInheritsBaseUrl:
    """SubAgentTool._make_llm must pass parent base_url to child when model is overridden."""

    def test_no_model_override_reuses_parent_llm(self):
        """When no model override, _make_llm returns the same parent LLM object."""
        parent = _make_parent_llm("http://localhost:8765/v1")
        tool = _make_tool(parent)
        result = tool._make_llm(None)
        assert result is parent

    def test_model_override_inherits_base_url(self):
        """When model is overridden, the new LLM client must use parent's base_url."""
        parent_base_url = "http://localhost:8765/v1"
        parent = _make_parent_llm(parent_base_url, model="glm-5.1")
        tool = _make_tool(parent)

        captured_kwargs: dict = {}

        def fake_create_llm_client(base_url, model, api_key):
            captured_kwargs["base_url"] = base_url
            captured_kwargs["model"] = model
            captured_kwargs["api_key"] = api_key
            child = MagicMock()
            child.base_url = base_url
            child.fallback_model = None
            return child

        with patch(
            "hermit_agent.tools.agent.subagent.SubAgentTool._make_llm",
            wraps=tool._make_llm,
        ):
            with patch(
                "hermit_agent.llm_client.create_llm_client",
                side_effect=fake_create_llm_client,
            ):
                child_llm = tool._make_llm("some-model")

        assert captured_kwargs["base_url"] == parent_base_url

    def test_model_override_inherits_api_key(self):
        """When model is overridden, the new LLM client must use parent's api_key."""
        parent = _make_parent_llm("http://localhost:8765/v1", api_key="secret-key")
        tool = _make_tool(parent)

        captured_kwargs: dict = {}

        def fake_create_llm_client(base_url, model, api_key):
            captured_kwargs["api_key"] = api_key
            child = MagicMock()
            child.base_url = base_url
            child.fallback_model = None
            return child

        with patch(
            "hermit_agent.llm_client.create_llm_client",
            side_effect=fake_create_llm_client,
        ):
            tool._make_llm("some-model")

        assert captured_kwargs["api_key"] == "secret-key"
