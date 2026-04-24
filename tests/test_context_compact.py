"""Regression tests for upgraded context compaction (XML-structured prompt + model profiles).

Coverage:
- COMPACT_PROFILES prefix resolution (longest-match wins, default fallback)
- XML skeleton + 9-section directive present in COMPACT_PROMPT
- PARTIAL_COMPACT_PROMPT exists
- Helper parameterisation (_extract_file_paths / _restore_files)
- Custom compact_instructions injection (settings integration)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.context import (
    COMPACT_PROFILES,
    COMPACT_PROMPT,
    ContextManager,
    DEFAULT_PROFILE,
    PARTIAL_COMPACT_PROMPT,
    _extract_file_paths,
    _resolve_profile,
    _restore_files,
)
from hermit_agent.llm_client import LLMResponse, OllamaClient


# ─── Profile resolution ─────────────────────────────────────────────


def test_resolve_profile_matches_prefix():
    """glm-5.1 must hit the glm-5 entry, not glm-4."""
    profile = _resolve_profile("glm-5.1-chat")
    assert profile is COMPACT_PROFILES["glm-5"]
    # Sanity check: glm-5 profile exposes all four knobs.
    for key in ("window", "msg_chars", "files", "file_lines"):
        assert key in profile


def test_resolve_profile_default():
    """Unknown model names fall back to DEFAULT_PROFILE."""
    profile = _resolve_profile("some-unknown-model-xyz")
    assert profile is DEFAULT_PROFILE


def test_resolve_profile_none_model():
    """None / empty model name returns DEFAULT_PROFILE."""
    assert _resolve_profile(None) is DEFAULT_PROFILE
    assert _resolve_profile("") is DEFAULT_PROFILE


def test_resolve_profile_longest_prefix_wins():
    """When multiple prefixes match, the longest one must be selected.

    Example: both 'glm-4' and 'glm-5' share the 'glm-' root. 'glm-5.1' should
    NOT be matched by a shorter 'glm' prefix if one existed.
    """
    # Use qwen3-coder — a 'qwen3-coder' profile must win over any shorter
    # fallback chain.
    profile = _resolve_profile("qwen3-coder:30b")
    assert profile is COMPACT_PROFILES["qwen3-coder"]


# ─── Compact prompt structure ───────────────────────────────────────


def test_compact_prompt_contains_xml_structure():
    """Base compact prompt exposes an <analysis> scratchpad and a <summary> block."""
    assert "<analysis>" in COMPACT_PROMPT
    assert "</analysis>" in COMPACT_PROMPT
    assert "<summary>" in COMPACT_PROMPT
    assert "</summary>" in COMPACT_PROMPT


def test_compact_prompt_contains_9_sections():
    """All nine section titles must appear in the compact prompt (case-insensitive)."""
    titles = [
        "Primary Request",
        "Key Technical Concepts",
        "Files and Code Sections",
        "Errors",
        "Problem Solving",
        "user messages",  # section 6 mentions user messages enumeration
        "Pending Tasks",
        "Current Work",
        "Optional Next Step",
    ]
    lowered_prompt = COMPACT_PROMPT.lower()
    for title in titles:
        assert title.lower() in lowered_prompt, f"missing section fragment: {title!r}"


def test_compact_prompt_emphasises_verbatim_quote():
    """Section 9 must demand verbatim quoting to preserve intent."""
    lowered = COMPACT_PROMPT.lower()
    assert "verbatim" in lowered or "direct quote" in lowered


def test_partial_compact_prompt_exists():
    """PARTIAL_COMPACT_PROMPT constant is exported and mentions recent scope."""
    assert isinstance(PARTIAL_COMPACT_PROMPT, str) and PARTIAL_COMPACT_PROMPT
    assert "<analysis>" in PARTIAL_COMPACT_PROMPT
    assert "<summary>" in PARTIAL_COMPACT_PROMPT
    # Must signal that earlier context is retained and only tail is summarised.
    assert "recent" in PARTIAL_COMPACT_PROMPT.lower() or "retained" in PARTIAL_COMPACT_PROMPT.lower()


# ─── Helper parameterisation ────────────────────────────────────────


def test_extract_file_paths_respects_limit():
    """_extract_file_paths must honour the limit= parameter rather than hardcoding 5."""
    messages = [
        {"role": "user", "content": f"see /tmp/file_{i}.py"} for i in range(12)
    ]
    paths = _extract_file_paths(messages, limit=8)
    assert len(paths) == 8


def test_extract_file_paths_default_is_five():
    """Legacy default remains 5 for backwards compatibility."""
    messages = [
        {"role": "user", "content": f"see /tmp/file_{i}.py"} for i in range(12)
    ]
    paths = _extract_file_paths(messages)
    assert len(paths) == 5


def test_restore_files_respects_max_lines():
    """_restore_files must truncate at max_lines= for large files."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        for i in range(500):
            fh.write(f"line_{i}\n")
        path = fh.name

    try:
        restored = _restore_files([path], max_chars_per_file=100000, max_lines=50)
        # Only the first 50 lines (line_0 .. line_49) must be present.
        assert "line_49" in restored
        assert "line_50" not in restored
        assert "line_499" not in restored
    finally:
        os.unlink(path)


# ─── LLM compact with profile + custom instructions ─────────────────


class _CaptureLLM(OllamaClient):
    """Stub that records the prompt it receives for inspection."""

    def __init__(self, model_name: str = "glm-5.1"):
        self.model = model_name
        self.captured_messages: list[dict] = []
        self.captured_system: str | None = None

    def chat(self, messages, system=None, tools=None, abort_event=None):
        self.captured_messages = list(messages)
        self.captured_system = system
        return LLMResponse(content="[fake summary]", tool_calls=[])

    def chat_stream(self, messages, system=None, tools=None, abort_event=None):
        yield from []


def _long_messages(n: int = 80) -> list[dict]:
    """Build enough messages to flip compact level above 2 regardless of profile."""
    msgs = [{"role": "user", "content": "original request"}]
    for i in range(n):
        msgs.append({"role": "assistant", "content": f"step {i}: " + ("x" * 600)})
    return msgs


def test_llm_compact_uses_profile_window(monkeypatch):
    """The number of conversation snippet lines passed to the LLM must match
    the resolved profile's `window` setting, not a hardcoded constant."""
    llm = _CaptureLLM(model_name="glm-4-air")
    cm = ContextManager(max_context_tokens=4000, llm=llm)

    # Force level-4 path by invoking _llm_compact directly.
    messages = _long_messages(n=120)
    cm._llm_compact(messages)

    sent = llm.captured_messages[0]["content"]
    # Count how many "[role]" entries appear after the prompt block.
    # glm-4 profile has window=60, so at most 60 snippet lines.
    role_count = sent.count("[assistant]") + sent.count("[user]")
    assert role_count <= COMPACT_PROFILES["glm-4"]["window"]


def test_llm_compact_msg_chars_follows_profile(monkeypatch):
    """Individual message trimming must use profile['msg_chars']."""
    llm = _CaptureLLM(model_name="qwen3-coder:30b")
    cm = ContextManager(max_context_tokens=4000, llm=llm)

    # A single very long message — trimmed length should equal profile msg_chars.
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "y" * 5000},
    ]
    cm._llm_compact(messages)

    sent = llm.captured_messages[0]["content"]
    profile = COMPACT_PROFILES["qwen3-coder"]
    # Ensure no individual snippet line is longer than msg_chars + role tag slack (say 40).
    for line in sent.splitlines():
        if line.startswith("[assistant]"):
            # strip role tag
            body = line[len("[assistant] "):]
            assert len(body) <= profile["msg_chars"]


def test_custom_instructions_injected(monkeypatch, tmp_path):
    """When settings.compact_instructions is set, it must appear in the prompt."""
    # Patch load_settings to return a custom instruction.
    import hermit_agent.context as ctx

    def fake_loader(cwd=None):
        return {"compact_instructions": "Focus on Django migrations and Slack hooks."}

    monkeypatch.setattr(ctx, "_load_compact_settings", fake_loader, raising=False)

    llm = _CaptureLLM()
    cm = ContextManager(max_context_tokens=4000, llm=llm)
    cm._llm_compact(_long_messages(n=20))

    sent = llm.captured_messages[0]["content"]
    assert "<compact_instructions>" in sent
    assert "Django migrations and Slack hooks" in sent


def test_no_custom_instructions_no_block(monkeypatch):
    """An empty compact_instructions must not inject an empty XML block."""
    import hermit_agent.context as ctx

    monkeypatch.setattr(
        ctx,
        "_load_compact_settings",
        lambda cwd=None: {"compact_instructions": "   "},
        raising=False,
    )

    llm = _CaptureLLM()
    cm = ContextManager(max_context_tokens=4000, llm=llm)
    cm._llm_compact(_long_messages(n=20))

    sent = llm.captured_messages[0]["content"]
    assert "<compact_instructions>" not in sent


# ─── Config integration ─────────────────────────────────────────────


def test_config_defaults_have_compact_instructions_key():
    """config.DEFAULTS must expose 'compact_instructions' (empty by default)."""
    from hermit_agent.config import DEFAULTS

    assert "compact_instructions" in DEFAULTS
    assert DEFAULTS["compact_instructions"] == ""


def test_config_env_var_maps_to_compact_instructions(monkeypatch):
    """HERMIT_COMPACT_INSTRUCTIONS env variable overrides settings."""
    from hermit_agent.config import load_settings

    monkeypatch.setenv("HERMIT_COMPACT_INSTRUCTIONS", "only summarise python files")
    cfg = load_settings()
    assert cfg.get("compact_instructions") == "only summarise python files"


# ─── Copyright sanity: prompt wording is not verbatim from upstream ──


def test_compact_prompt_is_rewritten(tmp_path):
    """No sentence from Claude Code's prompt.ts BASE_COMPACT_PROMPT may appear verbatim.

    We check a few distinctive sentences that would be a copyright smell if they leaked.
    """
    upstream_markers = [
        "Your task is to create a detailed summary of the conversation so far",
        "This summary should be thorough in capturing technical details",
        "Before providing your final summary, wrap your analysis in <analysis> tags",
        "Please provide your summary based on the conversation so far",
        "List ALL user messages that are not tool results",
    ]
    for marker in upstream_markers:
        assert marker not in COMPACT_PROMPT, f"verbatim upstream phrase detected: {marker!r}"
        assert marker not in PARTIAL_COMPACT_PROMPT, f"verbatim upstream phrase in PARTIAL: {marker!r}"
