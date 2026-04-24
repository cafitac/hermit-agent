"""Context window management — inspired by Claude Code's autoCompact.ts pattern.

Token estimation → summarize and compact conversation when threshold is reached.
Especially important for local LLMs which have small context windows.

This module implements:
- Level 1-4 compaction (snip / micro / collapse / full LLM summary).
- Model-specific profiles controlling window, per-message trimming, and
  file-restore budgets so a 200k-context Claude is not downsized to the same
  shape as a 32k qwen3-coder.
- XML-structured two-stage prompt (<analysis> scratchpad + <summary> block)
  that lets the model think before emitting the final structured summary.
- Optional user-supplied `compact_instructions` (from settings / env) that
  steer what the summariser should emphasise.

All prompt wording is authored in this module — no verbatim copying from any
upstream implementation.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .llm_client import LLMClientBase


def estimate_tokens(text: str) -> int:
    """Simple token estimation. Approx. ~4 chars/token for English, ~2 chars/token for Korean."""
    # Estimate conservatively without an exact tokenizer
    return len(text) // 3


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate the total tokens of the message list."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # tool_calls also consume tokens
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            total += estimate_tokens(str(func.get("arguments", "")))
            total += estimate_tokens(func.get("name", ""))
    return total


# ─── Model profiles ─────────────────────────────────────────────────
#
# `window`      — how many trailing conversation lines to feed the summariser.
# `msg_chars`   — per-message character trim applied before assembly.
# `files`       — number of distinct file paths to restore after compaction.
# `file_lines`  — lines of each restored file included in the rehydration block.
#
# Prefix matching uses the longest prefix that matches the model name
# (lowercased), so a ``glm-5.1-chat`` model hits the ``glm-5`` entry rather
# than an older ``glm-4`` one. Dict order is therefore irrelevant — see
# ``_resolve_profile``.
COMPACT_PROFILES: dict[str, dict[str, int]] = {
    "claude":      {"window": 200, "msg_chars": 4000, "files": 15, "file_lines": 300},
    "opus":        {"window": 200, "msg_chars": 4000, "files": 15, "file_lines": 300},
    "sonnet":      {"window": 150, "msg_chars": 3000, "files": 12, "file_lines": 250},
    "glm-5":       {"window": 100, "msg_chars": 2000, "files": 10, "file_lines": 200},
    "glm-4":       {"window": 60,  "msg_chars": 1200, "files": 8,  "file_lines": 150},
    "gpt-4":       {"window": 80,  "msg_chars": 1500, "files": 10, "file_lines": 180},
    "qwen3-coder": {"window": 50,  "msg_chars": 1000, "files": 7,  "file_lines": 120},
}

DEFAULT_PROFILE: dict[str, int] = {
    "window": 30,
    "msg_chars": 500,
    "files": 5,
    "file_lines": 100,
}


def _resolve_profile(model_name: str | None) -> dict[str, int]:
    """Return the compaction profile for ``model_name``.

    Longest matching prefix wins. Unknown / empty names fall back to
    ``DEFAULT_PROFILE``.
    """
    if not model_name:
        return DEFAULT_PROFILE
    name = model_name.lower()
    best_prefix: str | None = None
    for prefix in COMPACT_PROFILES:
        if name.startswith(prefix):
            if best_prefix is None or len(prefix) > len(best_prefix):
                best_prefix = prefix
    if best_prefix is None:
        return DEFAULT_PROFILE
    return COMPACT_PROFILES[best_prefix]


def _load_compact_settings(cwd: str | None = None) -> dict[str, Any]:
    """Load Hermit settings so that compaction picks up ``compact_instructions``.

    Isolated as a tiny helper so tests can monkeypatch it without needing the
    full ``load_settings`` machinery.
    """
    try:
        from .config import load_settings

        return load_settings(cwd=cwd)
    except Exception:
        return {}


# ─── Compact prompts (wording authored here, not copied upstream) ───
#
# Two-stage shape:
#   <analysis>   — private scratchpad. The summariser thinks step-by-step.
#   <summary>    — structured 9-section output that actually gets persisted.
#
# Keep both blocks mandatory — parsers downstream can strip <analysis> before
# re-inserting the summary into the new conversation.

_ANALYSIS_INSTRUCTIONS_BASE = """Before you commit to the final summary, draft
your thinking inside an <analysis> block. Walk the conversation turn by turn
and note:

- What the user asked for and how their request evolved.
- The concrete actions you took (tool calls, code you wrote, files you read).
- Any corrections or pushback the user gave — preserve the correction verbatim.
- Errors that surfaced and the fix that unblocked them.

Double-check that every required section below is backed by something in the
transcript before you close the <analysis> block."""

_ANALYSIS_INSTRUCTIONS_PARTIAL = """Only the tail of the conversation is being
summarised here — earlier context is retained upstream and must NOT be
re-summarised. Draft your reasoning inside an <analysis> block that focuses on
the recent turns and feeds the structured summary that follows."""

_SECTION_CHECKLIST = """1. Primary Request and Intent: spell out, in full, what the
   user is trying to accomplish. Preserve shifts in intent across turns.
2. Key Technical Concepts: enumerate frameworks, languages, libraries, patterns
   and domain terms referenced in the conversation.
3. Files and Code Sections: list every file path that was read, written, or
   discussed. For each one, explain why it matters and include the code
   snippets that were actually inspected or edited (full snippets where
   applicable, not paraphrased).
4. Errors and Fixes: describe each error that surfaced, the fix that resolved
   it, and — critically — any user feedback that redirected your approach.
5. Problem Solving: capture key decisions, trade-offs, and ongoing
   investigations.
6. All User Messages: enumerate every non-tool-result user message verbatim or
   near-verbatim. These drive intent; do not collapse them into a single
   paraphrase.
7. Pending Tasks: list outstanding work items the user explicitly asked for.
8. Current Work: describe, with precision, what was in flight right before the
   summary was requested. Mention exact files and code regions.
9. Optional Next Step: suggest the next action only if it follows directly from
   the most recent explicit request. Include verbatim direct quotes from the
   user's latest messages so task intent cannot drift on resume."""

_OUTPUT_SKELETON = """<example>
<analysis>
[Your step-by-step thinking — gets stripped before the summary is reused.]
</analysis>

<summary>
1. Primary Request and Intent:
   [...]

2. Key Technical Concepts:
   - [...]

3. Files and Code Sections:
   - <path>
     - why it matters: [...]
     - snippet: [...]

4. Errors and Fixes:
   - [...]

5. Problem Solving:
   [...]

6. All User Messages:
   - [...]

7. Pending Tasks:
   - [...]

8. Current Work:
   [...]

9. Optional Next Step:
   [direct quote from the user: "..."]
</summary>
</example>"""


COMPACT_PROMPT = f"""You are compacting a coding agent's conversation so it can
continue without losing context. Aim for fidelity over brevity — downstream
readers will rely on this summary as if it were the raw transcript.

{_ANALYSIS_INSTRUCTIONS_BASE}

Your <summary> block must contain exactly these nine sections, in order:

{_SECTION_CHECKLIST}

Emit both blocks — the <analysis> scratchpad first, followed by the <summary>
block. Reply with plain text only; do not call any tools. Follow this shape:

{_OUTPUT_SKELETON}
"""


PARTIAL_COMPACT_PROMPT = f"""You are compacting only the most recent portion of
a coding agent's conversation. Earlier messages are being kept intact and must
NOT be rewritten. Summarise just the tail so that, when prepended to those
retained messages, the full context is preserved.

{_ANALYSIS_INSTRUCTIONS_PARTIAL}

Your <summary> block must contain the same nine sections used by the full
compaction:

{_SECTION_CHECKLIST}

Emit both blocks — the <analysis> scratchpad first, followed by the <summary>
block. Reply with plain text only; do not call any tools. Follow this shape:

{_OUTPUT_SKELETON}
"""


def _extract_file_paths(messages: list[dict], limit: int = 5) -> list[str]:
    """Extract up to ``limit`` unique file paths last mentioned in the messages."""
    # Pattern matching for strings that look like absolute or relative paths
    path_pattern = re.compile(r"(?<!\w)(/[\w./-]+\.\w+|[\w./-]+/[\w./-]+\.\w+)(?!\w)")
    seen: dict[str, int] = {}  # path -> last seen index

    for idx, msg in enumerate(messages):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        for match in path_pattern.finditer(content):
            path = match.group(1)
            seen[path] = idx

    sorted_paths = sorted(seen, key=lambda p: seen[p], reverse=True)
    return sorted_paths[:limit]


def _restore_files(
    paths: list[str],
    max_chars_per_file: int = 5000,
    max_lines: int = 100,
) -> str:
    """Read up to ``max_lines`` from each listed file and concatenate the
    prefixes into a rehydration context block."""
    sections: list[str] = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = []
                for i, line in enumerate(fh):
                    if i >= max_lines:
                        break
                    lines.append(line)
            content = "".join(lines)[:max_chars_per_file]
            sections.append(f"[Restored file: {path}]\n{content}")
        except OSError:
            continue
    return "\n\n".join(sections)


def _restore_active_skills(messages: list[dict], max_chars_per_skill: int = 5000, max_total: int = 25000) -> str:
    """Reinject active skills after compression. Find skill execution traces in the message and restore contents."""
    try:
        from .skills import SkillRegistry

        registry = SkillRegistry()
    except Exception:
        return ""

    # Find the "Execute the following skill" pattern in the message
    active_skill_names: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and "Execute the following skill" in content:
            # Attempt to extract skill name
            for listed_skill in registry.list_skills():
                if listed_skill.content and listed_skill.content[:50] in content:
                    if listed_skill.name not in active_skill_names:
                        active_skill_names.append(listed_skill.name)

    if not active_skill_names:
        return ""

    sections: list[str] = []
    total = 0
    for name in active_skill_names[:5]:  # Up to 5
        restored_skill = registry.get(name)
        if restored_skill and restored_skill.content:
            chunk = restored_skill.content[:max_chars_per_skill]
            if total + len(chunk) > max_total:
                break
            sections.append(f"[Restored skill: {name}]\n{chunk}")
            total += len(chunk)

    return "\n\n".join(sections)


class ContextManager:
    """Context window management.

    Claude Code pattern:
    - autoCompact: token threshold = (context window) - 13,000
    - Circuit breaker: Stop compression attempts after 3 consecutive failures
"""

    def __init__(
        self,
        max_context_tokens: int = 32000,
        buffer_tokens: int | None = None,
        llm: LLMClientBase | None = None,
        threshold_ratio: float = 0.95,
        compact_start_ratio: float = 0.85,
    ):
        # §29 Bug 2: Dynamically adjust threshold to 75% of the context window.
        # If buffer_tokens is specified, maintain the legacy method (max - buffer).
        self.max_context_tokens = max_context_tokens
        if buffer_tokens is not None:
            self.buffer = buffer_tokens
            self.threshold = max_context_tokens - buffer_tokens
        else:
            self.threshold = int(max_context_tokens * threshold_ratio)
            self.buffer = max_context_tokens - self.threshold
        # compact trigger entry point = threshold * compact_start_ratio.
        # Never compact if the actual token count is below this value (prevents G25).
        self.compact_start_ratio = compact_start_ratio
        self.llm = llm
        self.consecutive_failures = 0
        self.max_failures = 3  # Circuit breaker

    def should_compact(self, messages: list[dict]) -> bool:
        if self.consecutive_failures >= self.max_failures:
            return False  # Circuit breaker triggered
        return estimate_messages_tokens(messages) >= self.threshold * self.compact_start_ratio

    def get_compact_level(self, messages: list[dict]) -> int:
        """0 = no compact needed, 1-4 = compact level."""
        if self.consecutive_failures >= self.max_failures:
            return 0  # Circuit breaker triggered
        tokens = estimate_messages_tokens(messages)
        start = self.threshold * self.compact_start_ratio
        if tokens < start:
            return 0
        if tokens < self.threshold * 0.9:
            return 1  # snip
        if tokens < self.threshold:
            return 2  # micro
        if tokens < self.threshold * 1.1:
            return 3  # collapse
        return 4  # full LLM summary

    def compact(self, messages: list[dict]) -> list[dict]:
        """Compress the conversation. Attempt step-by-step based on the level."""
        if not messages:
            return messages

        level = self.get_compact_level(messages)
        if level == 1:
            return self._snip_compact(messages)
        if level == 2:
            return self._micro_compact(messages)
        if level == 3:
            return self._collapse_compact(messages)
        if level == 4:
            if self.llm is not None:
                return self._llm_compact(messages)
            return self._simple_compact(messages)
        return messages

    def _snip_compact(self, messages: list[dict]) -> list[dict]:
        """Level 1: Remove tool result content older than the last 5 tool interactions.

        The first user message (original request) is always preserved.
"""
        tool_result_indices = [
            i for i, msg in enumerate(messages) if msg.get("role") == "tool" or msg.get("tool_call_id")
        ]

        if len(tool_result_indices) <= 3:
            return messages

        cutoff_indices = set(tool_result_indices[:-3])

        result = []
        for i, msg in enumerate(messages):
            if i in cutoff_indices:
                msg = dict(msg)
                original_len = len(str(msg.get("content", "")))
                tool_name = msg.get("name", "tool")
                msg["content"] = f"[snipped: {tool_name} result, {original_len} chars]"
                result.append(msg)
            else:
                result.append(msg)
        return result

    def _micro_compact(self, messages: list[dict]) -> list[dict]:
        """Level 2: Trim messages exceeding 2000 characters to the first 500 + last 500 characters."""
        result = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 2000:
                msg = dict(msg)
                omitted = len(content) - 1000
                msg["content"] = content[:500] + f"\n[...truncated {omitted} chars...]\n" + content[-500:]
            result.append(msg)
        return result

    def _collapse_compact(self, messages: list[dict]) -> list[dict]:
        """Level 3: Collapse 3 or more consecutive tool calls of the same type into a single summary."""
        result: list[dict] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            # Check tool_calls in assistant message
            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                result.append(msg)
                i += 1
                continue

            # Tool name of the current assistant message
            current_tool_name = tool_calls[0].get("function", {}).get("name", "") if tool_calls else ""

            # Collect consecutive assistant messages with the same tool name
            run_msgs = [msg]
            j = i + 1
            # A tool result message follows each tool call — skip it
            while j < len(messages):
                # Skip tool result message
                if messages[j].get("role") == "tool" or messages[j].get("tool_call_id"):
                    j += 1
                    continue
                next_msg = messages[j]
                next_tool_calls = next_msg.get("tool_calls", [])
                if not next_tool_calls:
                    break
                next_tool_name = next_tool_calls[0].get("function", {}).get("name", "")
                if next_tool_name != current_tool_name:
                    break
                run_msgs.append(next_msg)
                j += 1

            if len(run_msgs) >= 3:
                # Extract file paths or identifiers from the arguments of each call
                identifiers = []
                for rm in run_msgs:
                    for tc in rm.get("tool_calls", []):
                        args = tc.get("function", {}).get("arguments", "")
                        try:
                            parsed = json.loads(args) if isinstance(args, str) else args
                            # Use the first string value as the identifier
                            for v in parsed.values():
                                if isinstance(v, str):
                                    identifiers.append(v[:80])
                                    break
                        except Exception:
                            if args:
                                identifiers.append(str(args)[:80])

                summary_content = (
                    f"[Collapsed: {len(run_msgs)} {current_tool_name} calls."
                    + (f" Files: {', '.join(identifiers)}" if identifiers else "")
                    + "]"
                )
                result.append({"role": "assistant", "content": summary_content})
                # Also skip the tool result message (j is already advanced)
                i = j
            else:
                result.append(msg)
                i += 1

        return result

    def _simple_compact(self, messages: list[dict]) -> list[dict]:
        """Simple slicing without LLM (preserving only recent messages)."""
        # Preserve the first user message (original request) + the latest 10 messages
        first_user = None
        for msg in messages:
            if msg.get("role") == "user" and not msg.get("tool_call_id"):
                first_user = msg
                break

        recent = messages[-10:]
        if first_user and first_user not in recent:
            return [first_user, {"role": "system", "content": "[Earlier conversation compacted]"}, *recent]
        return recent

    def _llm_compact(self, messages: list[dict], partial: bool = False) -> list[dict]:
        """9-section structured summary compression using LLM + file restoration.

        ``partial=True`` summarises only the second half of the transcript and
        keeps the first half verbatim. Currently opt-in — the auto trigger in
        ``compact()`` still uses the full-summary path.
        """
        try:
            # Resolve model profile so that big-context models aren't squeezed
            # into small-context budgets.
            model_name = getattr(self.llm, "model", None) if self.llm else None
            profile = _resolve_profile(model_name)

            if partial and len(messages) >= 4:
                pivot = len(messages) // 2
                retained_head = messages[:pivot]
                tail_to_summarise = messages[pivot:]
                prompt_body = PARTIAL_COMPACT_PROMPT
                source_messages = tail_to_summarise
            else:
                retained_head = []
                prompt_body = COMPACT_PROMPT
                source_messages = messages

            # Convert conversation to text using the profile's per-message
            # character budget so small-context models don't blow up.
            conversation_text: list[str] = []
            for msg in source_messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    conversation_text.append(f"[{role}] {content[:profile['msg_chars']]}")

            # Tail-window trimming.
            windowed = conversation_text[-profile["window"]:]

            summary_request_content = prompt_body + "\n\n" + "\n".join(windowed)

            # Optional user-supplied steering instructions. Read here (not at
            # module import) so settings.json edits are picked up live.
            cfg = _load_compact_settings()
            custom = str(cfg.get("compact_instructions", "") or "").strip()
            if custom:
                summary_request_content += (
                    f"\n\n<compact_instructions>\n{custom}\n</compact_instructions>\n"
                )

            summary_request = [{"role": "user", "content": summary_request_content}]

            llm = self.llm
            if llm is None:
                return self._simple_compact(messages)

            response = llm.chat(
                messages=summary_request,
                system="You are a conversation summarizer. Be concise and factual.",
            )

            if response.content:
                self.consecutive_failures = 0

                # Restore the last mentioned files — budget follows profile.
                file_paths = _extract_file_paths(messages, limit=profile["files"])
                restored = _restore_files(file_paths, max_lines=profile["file_lines"])

                summary_content = f"[Conversation summary]\n{response.content}"
                if restored:
                    summary_content += f"\n\n{restored}"

                # Re-inject skill (7.7) — restore active skill content after compression
                skill_context = _restore_active_skills(messages)
                if skill_context:
                    summary_content += f"\n\n{skill_context}"

                summary_msg = {"role": "user", "content": summary_content}
                if partial and retained_head:
                    # Keep earlier messages verbatim; summary bridges them to
                    # the latest live message.
                    return [*retained_head, summary_msg, messages[-1]]
                return [summary_msg, messages[-1]]
        except Exception:
            self.consecutive_failures += 1

        # Fallback to simple slicing on failure
        return self._simple_compact(messages)
