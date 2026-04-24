"""Sub-agent execution tool (SubAgentTool).

Uses lazy import pattern to avoid circular dependencies:
- AgentLoop, LLMClientBase etc. are imported inside execute().
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from ..base import Tool, ToolResult


class SubAgentTool(Tool):
    """Sub-agent — delegate complex tasks to a child agent.

    Based on Claude Code's AgentTool (src/tools/AgentTool/) pattern:
    - Creates a new agent with independent context
    - Uses subagent_type to select specialized agents (explore, executor, reviewer, etc.)
    - Supports model override per task (haiku/sonnet/opus)
    - background=True for parallel async execution
    - Returns results to parent upon completion
    """
    name = "sub_agent"
    description = (
        "Spawn a specialized sub-agent for complex, independent tasks. "
        "Use subagent_type to select a specialized agent (explore=read-only search, "
        "executor=code implementation, reviewer=code review, debugger=error analysis, "
        "verifier=test verification, general-purpose=default). "
        "Use background=true for parallel execution — multiple agents can run simultaneously."
    )

    # subagent_type → system prompt mapping (Claude Code builtInAgents.ts pattern)
    _SYSTEM_PROMPTS: dict[str, str] = {}  # populated lazily from auto_agents

    def __init__(self, llm_client, tools_factory, cwd: str = ".", emitter=None, permission_checker=None):
        self._llm = llm_client
        self._tools_factory = tools_factory
        self._cwd = cwd
        self._emitter = emitter
        self._permission_checker = permission_checker
        # Background agent support: (results_list, lock) set by AgentLoop after construction
        self._bg_queue: tuple[list[dict[str, str]], threading.Lock] | None = None
        self._bg_notify: Callable[[str], None] | None = None

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task description for the sub-agent. Be specific and include all necessary context.",
                },
                "description": {
                    "type": "string",
                    "description": "Short (3-5 word) description of what the sub-agent will do.",
                },
                "subagent_type": {
                    "type": "string",
                    "description": (
                        "Agent specialization: 'general-purpose' (default), 'explore' (read-only search), "
                        "'executor' (code implementation with write access), 'reviewer' (code review), "
                        "'debugger' (error analysis), 'verifier' (test/verification)."
                    ),
                    "default": "general-purpose",
                },
                "model": {
                    "type": "string",
                    "description": "Model override: 'haiku' (fast/cheap), 'sonnet' (balanced), 'opus' (powerful). Omit to use current model.",
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background (parallel). Parent continues immediately; result delivered when done.",
                    "default": False,
                },
            },
            "required": ["prompt", "description"],
        }

    def _make_llm(self, model_override: str | None):
        """Return LLM with model override applied. Reuse parent LLM if no override."""
        if not model_override:
            return self._llm
        from ...llm_client import create_llm_client
        # Model alias → actual model name (MODEL_ROUTING pattern)
        resolved = self._llm.MODEL_ROUTING.get(model_override, model_override)
        sub_llm = create_llm_client(base_url=self._llm.base_url, model=resolved, api_key=self._llm.api_key)
        sub_llm.fallback_model = self._llm.fallback_model
        return sub_llm

    def _make_agent(self, subagent_type: str, llm, readonly: bool):
        """Create an AgentLoop matching the subagent_type."""
        from ...loop import AgentLoop
        from ...permissions import PermissionMode
        from ...auto_agents import (
            EXPLORE_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT,
            REVIEWER_SYSTEM_PROMPT, DEBUGGER_SYSTEM_PROMPT, VERIFIER_SYSTEM_PROMPT,
            TEST_ENGINEER_SYSTEM_PROMPT,
        )

        _type_map: dict[str, str | None] = {
            "general-purpose": None,
            "explore": EXPLORE_SYSTEM_PROMPT,
            "Explore": EXPLORE_SYSTEM_PROMPT,
            "plan": PLAN_SYSTEM_PROMPT,
            "Plan": PLAN_SYSTEM_PROMPT,
            "executor": None,
            "reviewer": REVIEWER_SYSTEM_PROMPT,
            "debugger": DEBUGGER_SYSTEM_PROMPT,
            "verifier": VERIFIER_SYSTEM_PROMPT,
            "test-engineer": TEST_ENGINEER_SYSTEM_PROMPT,
        }
        # Support OMC namespace format (e.g. "oh-my-claudecode:explore")
        short_type = subagent_type.split(":")[-1] if ":" in subagent_type else subagent_type
        system_prompt = _type_map.get(subagent_type) or _type_map.get(short_type)

        tools = self._tools_factory(self._cwd)
        if readonly:
            _ro = frozenset({"read_file", "glob", "grep"})
            tools = [t for t in tools if getattr(t, "name", None) in _ro]

        agent = AgentLoop(
            llm=llm,
            tools=tools,
            cwd=self._cwd,
            permission_mode=PermissionMode.ALLOW_READ,
            system_prompt=system_prompt,
        )
        agent.MAX_TURNS = 20
        agent.streaming = False
        if self._emitter:
            agent.emitter = self._emitter
        if self._permission_checker:
            agent.permission_checker = self._permission_checker
        return agent

    def _make_subagent_logger(self, subagent_type: str, description: str):
        """Derive a subagent logger from the parent session logger (§25 G2)."""
        parent = getattr(self._llm, "session_logger", None)
        if parent is None or not hasattr(parent, "create_subagent_logger"):
            return None
        import uuid as _uuid
        agent_id = _uuid.uuid4().hex[:12]
        try:
            return parent.create_subagent_logger(
                agent_id=agent_id,
                agent_type=subagent_type,
                description=description,
            )
        except Exception:
            return None

    def execute(self, input: dict[str, Any]) -> ToolResult:
        prompt = input["prompt"]
        description = input.get("description", "sub-agent task")
        subagent_type = input.get("subagent_type", "general-purpose")
        model_override = input.get("model")
        background = input.get("background", False)

        readonly = subagent_type in ("explore", "Explore", "plan", "Plan")
        llm = self._make_llm(model_override)

        # Create sub-agent specific JSONL + meta.json
        sub_logger = self._make_subagent_logger(subagent_type, description)
        # If llm is shared, session_logger is also shared. Even without a separate llm
        # instance, subagent logging is isolated via meta.json + jsonl files. The point
        # where sub_logger can be injected is when _make_llm falls back to reusing the
        # parent llm — in this case, we don't change _llm.
        if sub_logger is not None and llm is not self._llm:
            llm.session_logger = sub_logger

        if background:
            def _run_bg():
                try:
                    agent = self._make_agent(subagent_type, llm, readonly)
                    result = agent.run(prompt)
                except Exception as e:
                    result = f"Sub-agent error: {e}"
                if sub_logger is not None:
                    try:
                        sub_logger.finish(result_summary=str(result)[:500])
                    except Exception:
                        pass
                if self._bg_queue is not None:
                    with self._bg_queue[1]:
                        self._bg_queue[0].append({"description": description, "result": result})
                    if self._bg_notify is not None:
                        self._bg_notify(description)

            t = threading.Thread(target=_run_bg, daemon=True)
            t.start()
            print(f"\n\033[35m  [Background agent started: {description} ({subagent_type})]\033[0m")
            return ToolResult(content=f"[Background agent started: {description}. Result will be delivered when complete.]")

        print(f"\n\033[35m  [Sub-agent: {description} ({subagent_type})]\033[0m")
        try:
            agent = self._make_agent(subagent_type, llm, readonly)
            result = agent.run(prompt)
            print(f"\033[35m  [Sub-agent done: {description}]\033[0m")
            if sub_logger is not None:
                try:
                    sub_logger.finish(result_summary=result[:500])
                except Exception:
                    pass
            return ToolResult(content=result[:10000])
        except Exception as e:
            if sub_logger is not None:
                try:
                    sub_logger.finish(result_summary=f"error: {e}")
                except Exception:
                    pass
            return ToolResult(content=f"Sub-agent error: {e}", is_error=True)


__all__ = ['SubAgentTool']
