"""Context classification and injection logic, extracted from AgentLoop."""
from __future__ import annotations

import os
import re as _re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loop import AgentLoop

from .loop_context import _CLASSIFY_SYSTEM_PROMPT


class ContextInjector:
    """Handles LLM classification and user-message context injection for AgentLoop."""

    def __init__(self, agent: "AgentLoop") -> None:
        self._agent = agent

    def classify(self, user_message: str) -> str | None:
        """Call LLM with minimal prompt to classify task type.

        Retention decision (Option B-gamma, Plan 2026-04-18): kept pending Ollama
        KV cache benchmark. Do NOT remove without benchmark evidence.

        Returns response for simple questions, None for coding tasks (NEED_TOOLS).
        """
        agent = self._agent
        try:
            clean_msg = _re.sub(
                r'<learned_feedback>.*?</learned_feedback>\s*',
                '',
                user_message,
                flags=_re.DOTALL,
            ).strip()
            if not clean_msg:
                return None
            response = agent.llm.chat(
                messages=[{"role": "user", "content": clean_msg}],
                system=_CLASSIFY_SYSTEM_PROMPT,
                tools=[],
            )
            content = response.content or ""
            if response.usage and hasattr(agent, "token_totals"):
                agent.token_totals["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
                agent.token_totals["completion_tokens"] += response.usage.get("completion_tokens", 0)
            if "NEED_TOOLS" in content.upper():
                return None
            if not content.strip():
                return None
            return content
        except Exception:
            return None  # Classification failed -> safely proceed with full call

    def inject_seed_handoff(self, user_message: str) -> str:
        """Inject the latest session handoff into user_message if available.

        Best-effort: returns original user_message unchanged on any failure.
        """
        agent = self._agent
        seed_handoff = getattr(agent, "seed_handoff", True)
        env_disable = os.environ.get("HERMIT_SEED_HANDOFF", "1").lower() in ("0", "false", "no", "off")
        if not seed_handoff or env_disable:
            return user_message
        try:
            max_ctx = getattr(agent.context_manager, "max_context_tokens", 32000)
        except Exception:
            max_ctx = 32000
        if max_ctx < 16000:
            return user_message
        from pathlib import Path
        from .session_wrap import _pick_latest_handoff, _load_consumed, _mark_consumed

        handoffs_dir = Path(agent.cwd) / ".hermit" / "handoffs"
        try:
            consumed = _load_consumed(handoffs_dir)
            handoff_path = _pick_latest_handoff(handoffs_dir, consumed)
            if handoff_path:
                content = handoff_path.read_text(encoding="utf-8", errors="replace")
                if len(content) > 2000:
                    content = content[:2000] + "\n\n[...handoff truncated...]"
                user_message = f"<session-handoff>\n{content}\n</session-handoff>\n\n{user_message}"
                _mark_consumed(handoffs_dir, handoff_path.name)
        except Exception:
            pass  # best-effort: handoff injection must not disrupt the session
        return user_message
