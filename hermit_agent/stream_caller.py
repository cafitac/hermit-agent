"""Streaming LLM call logic, extracted from AgentLoop._call_streaming."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loop import AgentLoop
    from .llm_client import LLMResponse


class StreamingCaller:
    """Handles streaming LLM calls: chunk accumulation, reasoning display, token counting."""

    def __init__(self, agent: "AgentLoop") -> None:
        self._agent = agent

    def call(self) -> "LLMResponse | None":
        """Stream LLM response and return assembled LLMResponse, or None on interrupt/error."""
        from .llm_client import LLMResponse

        agent = self._agent
        try:
            gen = agent.llm.chat_stream(
                messages=agent.messages,
                tools=agent._tool_schemas(),
                system=agent.system_prompt,
                abort_event=agent.abort_event,
            )

            full_content = ""
            tool_calls = []
            usage_acc: dict | None = None
            _reasoning_started = False

            for chunk in gen:
                if chunk.type == "usage":
                    usage_acc = getattr(chunk, "usage", None)
                elif chunk.type == "reasoning":
                    if not _reasoning_started:
                        agent.emitter.progress("[Reasoning] Starting...")
                        agent.emitter.status_update(reasoning=True)
                        _reasoning_started = True
                elif chunk.type == "text":
                    if _reasoning_started:
                        agent.emitter.progress("[Reasoning] Finished.")
                        agent.emitter.status_update(reasoning=False)
                        _reasoning_started = False
                    full_content += chunk.text
                    agent.emitter.text(chunk.text)
                elif chunk.type == "tool_call_done" and chunk.tool_call:
                    tool_calls.append(chunk.tool_call)

            if usage_acc and hasattr(agent, "token_totals"):
                agent.token_totals["prompt_tokens"] += usage_acc.get("prompt_tokens", 0)
                agent.token_totals["completion_tokens"] += usage_acc.get("completion_tokens", 0)

            return LLMResponse(content=full_content or None, tool_calls=tool_calls, usage=usage_acc)

        except InterruptedError:
            # ESC interrupt — stream aborted. Handled by _run_loop top-of-loop check.
            agent.interrupted = True
            return None
        except Exception as e:
            agent.emitter.tool_result(f"[LLM streaming error: {e}]", is_error=True)
            return None
