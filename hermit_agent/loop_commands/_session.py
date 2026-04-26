"""Slash commands — session group."""
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ._registry import slash_command, SLASH_COMMANDS

if TYPE_CHECKING:
    from ..loop import AgentLoop

@slash_command("help", "Get help with using HermitAgent")
def cmd_help(agent: AgentLoop, args: str) -> str:
    lines = ["Available commands:"]
    for name, info in sorted(SLASH_COMMANDS.items()):
        lines.append(f"  /{name:12s} {info['description']}")
    return "\n".join(lines)


@slash_command("compact", "Compress conversation context")
def cmd_compact(agent: AgentLoop, args: str) -> str:
    from ..context import estimate_messages_tokens
    token_count = estimate_messages_tokens(agent.messages)
    before = len(agent.messages)
    agent.messages = agent.context_manager.compact(agent.messages)
    after = len(agent.messages)
    return f"Compacted: {before} → {after} messages (~{token_count} tokens)"


@slash_command("memory", "Manage persistent memory")
def cmd_memory(agent: AgentLoop, args: str) -> str:
    from ..memory import MemorySystem
    memory = MemorySystem()
    return memory.get_index()


@slash_command("cost", "Check token usage")
def cmd_cost(agent: AgentLoop, args: str) -> str:
    t = agent.token_totals
    inp = t.prompt_tokens
    out = t.completion_tokens
    cached = t.cached_tokens
    reasoning = t.reasoning_tokens
    total = inp + out
    cached_str = f" (+ {cached:,} cached)" if cached else ""
    reasoning_str = f" (reasoning {reasoning:,})" if reasoning else ""
    return (
        f"Token usage: total={total:,} input={inp:,}{cached_str} output={out:,}{reasoning_str}\n"
        f"Session: {agent.turn_count} turns | {len(agent.messages)} messages"
    )


@slash_command("clear", "Clear conversation history")
def cmd_clear(agent: AgentLoop, args: str) -> str:
    agent.messages.clear()
    agent.turn_count = 0
    return "Conversation cleared."


@slash_command("diff", "View git changes")
def cmd_diff(agent: AgentLoop, args: str) -> str:
    flag = args.strip() if args.strip() else "--stat"
    try:
        result = subprocess.run(
            ["git", "diff", flag],
            check=False,
            capture_output=True,
            text=True,
            cwd=agent.cwd,
            timeout=10,
        )
        return result.stdout.strip() or "No changes."
    except Exception as e:
        return f"Error: {e}"


@slash_command("context", "Show context window usage")
def cmd_context(agent: AgentLoop, args: str) -> str:
    from ..context import estimate_messages_tokens
    token_count = estimate_messages_tokens(agent.messages)
    max_ctx = agent.context_manager.max_context_tokens
    threshold = agent.context_manager.threshold
    pct = (token_count / max_ctx * 100) if max_ctx else 0
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    return (
        f"Context: [{bar}] {pct:.0f}%\n"
        f"Tokens: ~{token_count} / {max_ctx} (compact at {threshold})\n"
        f"Messages: {len(agent.messages)}"
    )


@slash_command("resume", "List or restore a previous session")
def cmd_resume(agent: AgentLoop, args: str) -> str:
    import time as _time

    from ..session import list_sessions, load_session

    if args.strip():
        saved = load_session(args.strip())
        if saved:
            agent.messages = saved.messages
            agent.session_id = saved.meta.session_id
            agent.turn_count = saved.meta.turn_count
            return f"Resumed: {saved.meta.session_id} ({saved.meta.turn_count} turns)"
        return f"Session not found: {args.strip()}"
    sessions = list_sessions()
    if not sessions:
        return "No saved sessions."
    lines = ["Saved sessions (use /resume <id>):"]
    for s in sessions:
        age = _time.time() - s.updated_at
        if age < 3600:
            age_str = f"{int(age / 60)}m ago"
        elif age < 86400:
            age_str = f"{int(age / 3600)}h ago"
        else:
            age_str = f"{int(age / 86400)}d ago"
        lines.append(f"  {s.session_id} | {s.turn_count} turns | {age_str} | {s.preview[:40]}")
    return "\n".join(lines)


@slash_command("wrap", "Save a session handoff artifact (summary, optional files/next-steps)")
def cmd_wrap(agent: AgentLoop, args: str) -> str:
    from ..session_wrap import build_handoff, save_handoff

    summary = args.strip() or f"Session {agent.session_id} — {agent.turn_count} turns"
    files_touched: list[str] = []
    try:
        files_touched = sorted(agent.auto_agents.modified_files)
    except Exception:
        pass
    content = build_handoff(summary=summary, files_touched=files_touched, next_steps=[])
    path = save_handoff(content=content, session_id=agent.session_id, cwd=agent.cwd)
    return f"Saved handoff: {path}"


@slash_command("status", "Show agent status: turns, tokens, modified files, error history")
def cmd_status(agent: AgentLoop, args: str) -> str:
    from ..context import estimate_messages_tokens

    token_count = estimate_messages_tokens(agent.messages)
    # Collect modified files and error history from auto_agents tracker
    modified = list(agent.auto_agents.changed_files) if hasattr(agent.auto_agents, "changed_files") else []
    errors = list(agent.auto_agents.recent_errors) if hasattr(agent.auto_agents, "recent_errors") else []
    t = agent.token_totals
    inp = t.prompt_tokens
    out = t.completion_tokens
    cached = t.cached_tokens
    reasoning = t.reasoning_tokens
    total = inp + out
    cached_str = f" (+ {cached:,} cached)" if cached else ""
    reasoning_str = f" (reasoning {reasoning:,})" if reasoning else ""
    max_ctx = agent.context_manager.max_context_tokens
    ctx_pct_left = int((1 - token_count / max_ctx) * 100) if max_ctx else 0
    lines = [
        f"Session: {agent.session_id}",
        f"Turns: {agent.turn_count} / {agent.MAX_TURNS}",
        f"Messages: {len(agent.messages)}",
        f"Context window: {ctx_pct_left}% left ({token_count:,} used / {max_ctx:,})",
        f"Token usage: total={total:,} input={inp:,}{cached_str} output={out:,}{reasoning_str}",
        f"CWD: {agent.cwd}",
        f"Model: {agent.llm.model}",
    ]
    if modified:
        lines.append(f"Modified files ({len(modified)}):")
        for f in modified[:10]:
            lines.append(f"  {f}")
    else:
        lines.append("Modified files: none")
    if errors:
        lines.append(f"Recent errors ({len(errors)}):")
        for tool_name, msg in errors[-5:]:
            lines.append(f"  [{tool_name}] {msg[:80]}")
    else:
        lines.append("Recent errors: none")
    return "\n".join(lines)


@slash_command("log", "Show recent git log (last 10 commits)")
def cmd_log(agent: AgentLoop, args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            check=False,
            capture_output=True,
            text=True,
            cwd=agent.cwd,
            timeout=10,
        )
        return result.stdout.strip() or "No commits yet."
    except Exception as e:
        return f"Error: {e}"

