from __future__ import annotations

from hermit_agent.gateway.task_models import AUTO_MODEL_SENTINEL, normalize_requested_model
from hermit_agent.gateway.task_runner import _is_auto_model


def test_normalize_requested_model_uses_auto_sentinel_for_blank_inputs():
    assert normalize_requested_model("") == AUTO_MODEL_SENTINEL
    assert normalize_requested_model("   ") == AUTO_MODEL_SENTINEL
    assert normalize_requested_model(None) == AUTO_MODEL_SENTINEL


def test_normalize_requested_model_preserves_explicit_model_names():
    assert normalize_requested_model("glm-5.1") == "glm-5.1"
    assert normalize_requested_model("  codex-mini  ") == "codex-mini"


def test_is_auto_model_accepts_auto_aliases():
    assert _is_auto_model("") is True
    assert _is_auto_model("   ") is True
    assert _is_auto_model("auto") is True
    assert _is_auto_model("__auto__") is True


def test_is_auto_model_rejects_explicit_model_names():
    assert _is_auto_model("glm-5.1") is False
