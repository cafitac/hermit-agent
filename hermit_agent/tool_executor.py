"""Tool dispatch and execution logic, extracted from AgentLoop."""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loop import AgentLoop
    from .tools import ToolResult

_logger = logging.getLogger(__name__)


def _tool_detail(name: str, arguments: dict) -> str:
    """Argument summary for tool call display."""
    if name == "bash":
        return arguments.get("command", "")
    if name in ("read_file", "edit_file", "write_file"):
        return arguments.get("path", "")
    if name == "glob" or name == "grep":
        return arguments.get("pattern", "")
    if name == "sub_agent":
        return arguments.get("description", "")
    return str(arguments)[:80]


def _tool_result_preview(result: "ToolResult") -> str:
    """Pass tool result to UI. Rendering is limited on the UI side."""
    return result.content[:2000]


class ToolExecutor:
    """Handles single-tool dispatch: permission checks, hooks, execution, result capping."""

    def __init__(self, agent: "AgentLoop") -> None:
        self._agent = agent

    def execute_tool(self, name: str, arguments: dict) -> "ToolResult":
        from .hooks import HookEvent
        from .tools import ToolResult

        agent = self._agent
        tool = agent.tools.get(name)
        if not tool:
            tool = agent._all_tools.get(name)
            if tool:
                agent._used_extended_tools = True
            else:
                return ToolResult(content=f"Unknown tool: {name}", is_error=True)

        pre_result = agent.hook_runner.run_hooks(HookEvent.PRE_TOOL_USE, name, arguments)
        if pre_result.modified_input:
            arguments = pre_result.modified_input
        if pre_result.action.value == "deny":
            return ToolResult(content=f"[Hook blocked] {pre_result.message}", is_error=True)

        denied, messages = agent.plugin_registry.run_pre_hooks(name, json.dumps(arguments))
        if denied:
            return ToolResult(content=f"[Plugin blocked] {'; '.join(messages)}", is_error=True)

        if not agent.permission_checker.check(name, arguments, tool.is_read_only):
            return ToolResult(
                content=(
                    f"Permission denied for {name}. "
                    "Do NOT retry the same command. "
                    "Use ask_user_question to inform the user that permission was denied "
                    "and ask whether they want to allow it or suggest an alternative approach."
                ),
                is_error=True,
            )

        error = tool.validate(arguments)
        if error:
            return ToolResult(content=error, is_error=True)

        guard_result = agent._edit_loop_guard(name, arguments)
        if guard_result is not None:
            return guard_result

        result = tool.execute(arguments)

        MAX_RESULT_CHARS = 10000
        if len(result.content) > MAX_RESULT_CHARS:
            saved_path = os.path.join(agent.scratchpad_dir, f"tool_result_{name}_{agent.turn_count}.txt")
            try:
                with open(saved_path, "w") as f:
                    f.write(result.content)
                truncated = result.content[:MAX_RESULT_CHARS]
                result = ToolResult(
                    content=f"{truncated}\n\n[Full result ({len(result.content)} chars) saved to {saved_path}]",
                    is_error=result.is_error,
                )
            except Exception as exc:
                _logger.debug("large result save failed: %s", exc)
                truncated = result.content[:MAX_RESULT_CHARS]
                result = ToolResult(
                    content=f"{truncated}\n\n[Truncated: {len(result.content)} chars]",
                    is_error=result.is_error,
                )

        agent.hook_runner.run_hooks(HookEvent.POST_TOOL_USE, name, arguments, result.content)
        agent.plugin_registry.run_post_hooks(name, json.dumps(arguments), result.content, result.is_error)

        if agent._on_tool_result is not None:
            try:
                agent._on_tool_result(name, result.content, result.is_error)
            except Exception as exc:
                _logger.debug("on_tool_result callback: %s", exc)

        if name in ("edit_file", "write_file") and not result.is_error:
            path = arguments.get("path", "")
            if path:
                agent.auto_agents.track_file_change(path)
        if result.is_error:
            agent.auto_agents.track_error(name, result.content)

        agent._track_loop_state(name, arguments, result)

        return result

    def partition_tool_calls(self, tool_calls: list) -> list[tuple[list, bool]]:
        """Batch consecutive concurrency-safe tools. Returns list of (batch, is_parallel)."""
        agent = self._agent
        batches: list[tuple[list, bool]] = []
        current_batch: list = []
        current_safe: bool | None = None

        for tc in tool_calls:
            tool = agent.tools.get(tc.name)
            is_safe = tool.is_concurrent_safe if tool else False

            if current_safe is None:
                current_safe = is_safe
                current_batch = [tc]
            elif is_safe == current_safe:
                current_batch.append(tc)
            else:
                batches.append((current_batch, current_safe))
                current_batch = [tc]
                current_safe = is_safe

        if current_batch:
            batches.append((current_batch, current_safe or False))

        return batches

    def execute_tool_calls(self, tool_calls: list) -> bool:
        """Execute tool calls — concurrency-safe tools run in parallel, others sequentially.

        Returns True if paused (ask_user_question), False if completed normally.
        """
        import json as _json
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .context import estimate_messages_tokens

        agent = self._agent
        batches = self.partition_tool_calls(tool_calls)

        for batch, is_parallel in batches:
            if is_parallel and len(batch) > 1:
                results: dict[str, "ToolResult"] = {}
                for tc in batch:
                    agent.emitter.tool_use(tc.name, _tool_detail(tc.name, tc.arguments))
                    agent._lifecycle.log_tool_use(tc)

                with ThreadPoolExecutor(max_workers=min(len(batch), 5)) as pool:
                    futures = {pool.submit(self.execute_tool, tc.name, tc.arguments): tc for tc in batch}
                    for future in as_completed(futures):
                        tc = futures[future]
                        results[tc.id] = future.result()
                        agent.emitter.tool_result(_tool_result_preview(results[tc.id]), results[tc.id].is_error)
                        agent._lifecycle.log_tool_result(tc.id, results[tc.id])

                for tc in batch:
                    agent.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": results[tc.id].content,
                    })
            else:
                for tc in batch:
                    agent.emitter.tool_use(tc.name, _tool_detail(tc.name, tc.arguments))
                    agent._lifecycle.log_tool_use(tc)
                    result = self.execute_tool(tc.name, tc.arguments)
                    agent._tool_call_count += 1
                    agent.emitter.tool_result(_tool_result_preview(result), result.is_error)
                    agent._lifecycle.log_tool_result(tc.id, result)

                    agent.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.content,
                    })

                    if tc.name == "ask_user_question" and not result.is_error:
                        tool_inst = agent.tools.get(tc.name)
                        is_mcp_mode = getattr(tool_inst, "_q_out", None) is not None
                        if not is_mcp_mode:
                            question = tc.arguments.get("question", "")
                            options = tc.arguments.get("options", [])
                            if isinstance(options, str):
                                try:
                                    options = _json.loads(options)
                                except (_json.JSONDecodeError, ValueError):
                                    options = [options]
                            parts = [question]
                            if options:
                                parts.append("")
                                for i, opt in enumerate(options, 1):
                                    parts.append(f"  {i}. {opt}")
                            agent.emitter.text("\n".join(parts))
                            return True

        token_count = estimate_messages_tokens(agent.messages)
        max_ctx = agent.context_manager.max_context_tokens
        ctx_pct = int(token_count / max_ctx * 100) if max_ctx else 0
        agent.emitter.status_update(
            turns=agent.turn_count,
            ctx_pct=min(ctx_pct, 100),
            tokens=token_count,
            model=agent.llm.model,
        )
        return False

