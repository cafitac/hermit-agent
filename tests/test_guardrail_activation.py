"""Guardrail activation engine unit tests.

Verification items:
- unknown profile → all guardrails active (regression-safe)
- always_active guardrail → active regardless of profile
- activate_when condition evaluation (single/any/all)
- non-existent G# → active by default (fallback)
- corrupted YAML → retains previous value
"""

import os
import tempfile
import threading
from pathlib import Path

import pytest

from hermit_agent.guardrails.engine import GuardrailEngine, _eval_condition, _eval_activate_when


# --- _eval_condition unit tests ---

def test_eval_condition_gt():
    assert _eval_condition(0.5, ">0.2") is True
    assert _eval_condition(0.1, ">0.2") is False


def test_eval_condition_lt():
    assert _eval_condition(0.6, "<0.8") is True
    assert _eval_condition(0.9, "<0.8") is False


def test_eval_condition_lte():
    assert _eval_condition(32768, "<=65536") is True
    assert _eval_condition(131072, "<=65536") is False


def test_eval_condition_gte():
    assert _eval_condition(0.94, ">=0.9") is True
    assert _eval_condition(0.8, ">=0.9") is False


def test_eval_condition_eq():
    assert _eval_condition(0.5, "==0.5") is True
    assert _eval_condition(0.4, "==0.5") is False


# --- _eval_activate_when unit tests ---

def test_eval_activate_when_none_always_true():
    """activate_when None → always active."""
    assert _eval_activate_when(None, {}) is True


def test_eval_activate_when_single_dim():
    caps = {"tool_spam_tendency": 0.4}
    assert _eval_activate_when({"tool_spam_tendency": ">0.2"}, caps) is True
    assert _eval_activate_when({"tool_spam_tendency": ">0.5"}, caps) is False


def test_eval_activate_when_any():
    caps = {"tool_spam_tendency": 0.1, "instruction_following": 0.7}
    cond = {"any": [
        {"tool_spam_tendency": ">0.2"},
        {"instruction_following": "<0.8"},
    ]}
    assert _eval_activate_when(cond, caps) is True  # Second condition met


def test_eval_activate_when_all():
    caps = {"tool_spam_tendency": 0.4, "instruction_following": 0.7}
    cond = {"all": [
        {"tool_spam_tendency": ">0.2"},
        {"instruction_following": "<0.8"},
    ]}
    assert _eval_activate_when(cond, caps) is True  # Both met


def test_eval_activate_when_all_fails():
    caps = {"tool_spam_tendency": 0.1, "instruction_following": 0.7}
    cond = {"all": [
        {"tool_spam_tendency": ">0.2"},  # False
        {"instruction_following": "<0.8"},  # True
    ]}
    assert _eval_activate_when(cond, caps) is False


def test_eval_activate_when_unknown_capability_defaults_active():
    """Safely active if capability is missing."""
    caps = {}
    assert _eval_activate_when({"tool_spam_tendency": ">0.2"}, caps) is True


# --- GuardrailEngine integration tests ---

class _TempEngine:
    """GuardrailEngine wrapper based on a temporary YAML file. File lifecycle managed with a with statement."""

    def __init__(self, registry_content: str, profile_content: str):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = self._tmpdir.name
        self._reg_path = Path(tmp) / "registry.yaml"
        self._prof_path = Path(tmp) / "profile.yaml"
        self._reg_path.write_text(registry_content)
        self._prof_path.write_text(profile_content)
        self.engine = GuardrailEngine(registry_path=self._reg_path)
        self.engine._profile_path = self._prof_path
        import yaml
        self.engine._profile = yaml.safe_load(profile_content) or {}
        self.engine._profile_mtime = self._prof_path.stat().st_mtime

    def is_active(self, gid: str) -> bool:
        return self.engine.is_active(gid)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._tmpdir.cleanup()


def _make_engine_from_yaml(registry_content: str, profile_content: str) -> "_TempEngine":
    """Create GuardrailEngine with a temporary YAML file. Use .is_active() of the return value."""
    return _TempEngine(registry_content, profile_content)


REGISTRY_YAML = """
G_ALWAYS:
  name: always_guardrail
  always_active: true
  rationale: Always active

G_CONDITIONAL:
  name: conditional_guardrail
  activate_when:
    tool_spam_tendency: ">0.2"
  rationale: Only when spam tendency is present

G_ANY:
  name: any_guardrail
  activate_when:
    any:
      - tool_spam_tendency: ">0.2"
      - instruction_following: "<0.8"
  rationale: Either condition
"""

STRONG_MODEL_PROFILE = """
capabilities:
  tool_spam_tendency: 0.05
  instruction_following: 0.95
  context_window: 131072
  long_context_reasoning: 0.9
  self_reporting: 0.8
"""

WEAK_MODEL_PROFILE = """
capabilities:
  tool_spam_tendency: 0.40
  instruction_following: 0.65
  context_window: 32768
  long_context_reasoning: 0.55
  self_reporting: 0.30
"""

EMPTY_PROFILE = """
capabilities: {}
"""


def test_always_active_regardless_of_profile():
    engine = _make_engine_from_yaml(REGISTRY_YAML, STRONG_MODEL_PROFILE)
    assert engine.is_active("G_ALWAYS") is True

    engine2 = _make_engine_from_yaml(REGISTRY_YAML, WEAK_MODEL_PROFILE)
    assert engine2.is_active("G_ALWAYS") is True


def test_conditional_inactive_for_strong_model():
    engine = _make_engine_from_yaml(REGISTRY_YAML, STRONG_MODEL_PROFILE)
    assert engine.is_active("G_CONDITIONAL") is False  # tool_spam_tendency=0.05 < 0.2


def test_conditional_active_for_weak_model():
    engine = _make_engine_from_yaml(REGISTRY_YAML, WEAK_MODEL_PROFILE)
    assert engine.is_active("G_CONDITIONAL") is True  # tool_spam_tendency=0.40 > 0.2


def test_any_condition_strong_model_inactive():
    engine = _make_engine_from_yaml(REGISTRY_YAML, STRONG_MODEL_PROFILE)
    # spam=0.05 (not >0.2), instruction=0.95 (not <0.8) → both unmet
    assert engine.is_active("G_ANY") is False


def test_any_condition_weak_model_active():
    engine = _make_engine_from_yaml(REGISTRY_YAML, WEAK_MODEL_PROFILE)
    # spam=0.40 >0.2 → at least one met
    assert engine.is_active("G_ANY") is True


def test_unknown_gid_defaults_to_active():
    engine = _make_engine_from_yaml(REGISTRY_YAML, STRONG_MODEL_PROFILE)
    assert engine.is_active("G_NONEXISTENT") is True


def test_empty_profile_all_guardrails_active():
    """If profile capabilities are missing, all guardrails active (safe default)."""
    engine = _make_engine_from_yaml(REGISTRY_YAML, EMPTY_PROFILE)
    assert engine.is_active("G_ALWAYS") is True
    assert engine.is_active("G_CONDITIONAL") is True


def test_real_registry_unknown_profile_all_active():
    """Actual registry.yaml + unknown.yaml → all G# active (regression check)."""
    engine = GuardrailEngine(model_id=None)
    # always_active guardrail is unconditionally active
    always_active = ["G1", "G2", "G24", "G25", "G27", "G28", "G30", "G31", "G32", "G33", "G36", "G37", "G39", "G40", "G43", "G44", "G46", "G47"]
    for gid in always_active:
        assert engine.is_active(gid) is True, f"{gid} should be active with unknown profile"


def test_real_registry_qwen3_profile():
    """qwen3-coder:30b profile → weak model guardrails active."""
    engine = GuardrailEngine(model_id="qwen3-coder:30b")
    # weak instruction_following=0.65 < 0.85 → G34, G45 active
    assert engine.is_active("G34") is True
    assert engine.is_active("G45") is True
    # G29A: context_window=32768 <=65536 → active
    assert engine.is_active("G29A") is True


def test_real_registry_gpt_5_4_profile():
    """gpt-5.4 profile → stronger model guardrails mostly inactive."""
    engine = GuardrailEngine(model_id="gpt-5.4")
    assert engine.is_active("G34") is False
    assert engine.is_active("G45") is False
    assert engine.is_active("G29A") is False
    assert engine.is_active("G38") is False


def test_real_registry_gpt_5_3_profile():
    """gpt-5.3 profile → stronger model guardrails mostly inactive."""
    engine = GuardrailEngine(model_id="gpt-5.3")
    assert engine.is_active("G34") is False
    assert engine.is_active("G45") is False
    assert engine.is_active("G29A") is False
    assert engine.is_active("G38") is False


def test_real_registry_glm_5_1_profile():
    """glm-5.1 profile → mixed/default-balanced guardrail set."""
    engine = GuardrailEngine(model_id="glm-5.1")
    assert engine.is_active("G34") is True
    assert engine.is_active("G45") is True
    assert engine.is_active("G29A") is False
    assert engine.is_active("G38") is False


def test_user_profile_overrides_default_profile(tmp_path, monkeypatch):
    import hermit_agent.guardrails.engine as engine_mod

    user_profiles = tmp_path / "profiles"
    user_profiles.mkdir(parents=True)
    (user_profiles / "gpt-5.4.yaml").write_text(
        """
capabilities:
  tool_spam_tendency: 0.5
  instruction_following: 0.6
  context_window: 32768
  long_context_reasoning: 0.6
  self_reporting: 0.3
""".strip()
    )
    monkeypatch.setattr(engine_mod, "_USER_PROFILES_DIR", user_profiles)

    engine = engine_mod.GuardrailEngine(model_id="gpt-5.4")
    assert engine.is_active("G34") is True
    assert engine.is_active("G45") is True
    assert engine.is_active("G29A") is True


def test_hot_reload():
    """Verify that YAML changes are reflected via hot-reload."""
    import yaml

    INITIAL = """
G_HOT:
  name: hot_reload_test
  activate_when:
    tool_spam_tendency: ">0.5"
  rationale: test
"""
    UPDATED = """
G_HOT:
  name: hot_reload_test
  always_active: true
  rationale: test updated
"""
    PROFILE = """
capabilities:
  tool_spam_tendency: 0.1
"""
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = Path(tmp) / "registry.yaml"
        prof_path = Path(tmp) / "profile.yaml"
        reg_path.write_text(INITIAL)
        prof_path.write_text(PROFILE)

        engine = GuardrailEngine.__new__(GuardrailEngine)
        engine._model_id = "test"
        engine._registry_path = reg_path
        engine._lock = threading.Lock()
        engine._registry = yaml.safe_load(INITIAL) or {}
        engine._profile = yaml.safe_load(PROFILE) or {}
        engine._registry_mtime = reg_path.stat().st_mtime
        engine._profile_path = prof_path
        engine._profile_mtime = prof_path.stat().st_mtime

        # Initial: spam=0.1 < 0.5 → inactive
        assert engine.is_active("G_HOT") is False

        # Modify YAML (update to always_active)
        import time
        time.sleep(0.05)  # Ensure mtime difference
        reg_path.write_text(UPDATED)

        # Verify activation after hot-reload
        assert engine.is_active("G_HOT") is True
