"""Slash commands for HermitAgent — registered via @slash_command decorator.

All cmd_* functions take (agent: AgentLoop, args: str) -> str.
AgentLoop is imported lazily via TYPE_CHECKING to avoid circular imports.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from .version import VERSION

if TYPE_CHECKING:
    from .loop import AgentLoop

from .loop_context import _write_task_state, _read_task_state, _find_project_config, _find_rules

# --- Slash Commands (Claude Code compatible) ---------------------------------

SLASH_COMMANDS = {}

# Special return values: commands that trigger agent execution
TRIGGER_AGENT = "__trigger_agent__"
TRIGGER_AGENT_SINGLE = "__trigger_agent_single__"  # Interactive mode: run 1 turn only


def slash_command(name: str, description: str):
    def decorator(func):
        SLASH_COMMANDS[name] = {"func": func, "description": description}
        return func

    return decorator


# --- Claude Code Compatible Commands -----------------------------------------


@slash_command("help", "Get help with using HermitAgent")
def cmd_help(agent: AgentLoop, args: str) -> str:
    lines = ["Available commands:"]
    for name, info in sorted(SLASH_COMMANDS.items()):
        lines.append(f"  /{name:12s} {info['description']}")
    return "\n".join(lines)


@slash_command("compact", "Compress conversation context")
def cmd_compact(agent: AgentLoop, args: str) -> str:
    token_count = estimate_messages_tokens(agent.messages)
    before = len(agent.messages)
    agent.messages = agent.context_manager.compact(agent.messages)
    after = len(agent.messages)
    return f"Compacted: {before} → {after} messages (~{token_count} tokens)"


@slash_command("memory", "Manage persistent memory")
def cmd_memory(agent: AgentLoop, args: str) -> str:
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


@slash_command("model", "Show or change model")
def cmd_model(agent: AgentLoop, args: str) -> str:
    if args.strip():
        new_model = args.strip()
        agent.llm.model = new_model
        # Save as default model
        from .memory import MemorySystem

        mem = MemorySystem()
        mem.save("default_model", f"Default model: {new_model}", "feedback", f"User prefers {new_model}")
        return f"Model changed to: {agent.llm.model}"

    # Query available model list
    models_info = ""
    try:
        import requests

        resp = requests.get(f"{agent.llm.base_url}/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        available = [m["id"] for m in data.get("data", [])]
        if available:
            models_info = "\nAvailable models:\n" + "\n".join(f"  - {m}" for m in available)
    except Exception:
        pass

    return f"Current model: {agent.llm.model}{models_info}\n\nUsage: /model <name> to switch"


@slash_command("config", "Show current configuration")
def cmd_config(agent: AgentLoop, args: str) -> str:
    return (
        f"Model: {agent.llm.model}\n"
        f"API: {agent.llm.base_url}\n"
        f"CWD: {agent.cwd}\n"
        f"Permission: {agent.permission_checker.mode.value}\n"
        f"Streaming: {'on' if agent.streaming else 'off'}\n"
        f"Max turns: {agent.MAX_TURNS}\n"
        f"Max context: {agent.context_manager.max_context_tokens}\n"
        f"Session: {agent.session_id}"
    )


@slash_command("context", "Show context window usage")
def cmd_context(agent: AgentLoop, args: str) -> str:
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

    from .session import list_sessions, load_session

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


@slash_command("commit", "Create a git commit")
def cmd_commit(agent: AgentLoop, args: str) -> str:
    agent.messages.append(
        {
            "role": "user",
            "content": "Run git status to review changes, then create a well-described git commit for all staged changes. If nothing is staged, stage the relevant files first. Write a concise commit message in imperative mood.",
        }
    )
    return TRIGGER_AGENT


@slash_command("review", "Review code changes")
def cmd_review(agent: AgentLoop, args: str) -> str:
    agent.messages.append(
        {
            "role": "user",
            "content": "Review the current git diff. For each change, check: logic correctness, error handling, edge cases, code style. Rate issues as P1 (must fix), P2 (should fix), P3 (nice to have). Be specific with file:line references.",
        }
    )
    return TRIGGER_AGENT


@slash_command("skills", "List available skills")
def cmd_skills(agent: AgentLoop, args: str) -> str:
    from .skills import SkillRegistry

    registry = SkillRegistry()
    skills = registry.list_skills()
    if not skills:
        return "No skills available. Add skills in ~/.hermit/skills/<name>/SKILL.md"
    lines = ["Available skills:"]
    for s in skills:
        lines.append(f"  /{s.name:12s} [{s.source}] {s.description}")
    return "\n".join(lines)


@slash_command("hooks", "Show configured hooks")
def cmd_hooks(agent: AgentLoop, args: str) -> str:
    hooks = agent.hook_runner.hooks
    if not hooks:
        return "No hooks configured. Edit ~/.hermit/hooks.json to add hooks."
    lines = ["Configured hooks:"]
    for h in hooks:
        cond = f' if "{h.condition}"' if h.condition else ""
        lines.append(f"  {h.event.value} {h.tool}{cond} → {h.action.value}")
        if h.message:
            lines.append(f"    message: {h.message}")
    return "\n".join(lines)


@slash_command("init", "Initialize HERMIT.md in current directory")
def cmd_init(agent: AgentLoop, args: str) -> str:
    config_path = os.path.join(agent.cwd, "HERMIT.md")
    if os.path.exists(config_path):
        return f"HERMIT.md already exists at {config_path}"

    template = """# Project Instructions

This file is the configuration file that HermitAgent references when working on this project.

## Project Overview

- Describe the project here

## Code Rules

- Specify the languages, frameworks, and conventions used

## Directory Structure

- Describe the key directories and their roles
"""
    with open(config_path, "w") as f:
        f.write(template)
    return f"Created {config_path}. Edit this file to customize HermitAgent's behavior for this project."


@slash_command("doctor", "Diagnose HermitAgent setup (HERMIT.md, hooks, skills, permissions)")
def cmd_doctor_diag(agent: AgentLoop, args: str) -> str:
    from .doctor import run_diagnostics

    return run_diagnostics(cwd=agent.cwd).format()


@slash_command("wrap", "Save a session handoff artifact (summary, optional files/next-steps)")
def cmd_wrap(agent: AgentLoop, args: str) -> str:
    from .session_wrap import build_handoff, save_handoff

    summary = args.strip() or f"Session {agent.session_id} — {agent.turn_count} turns"
    files_touched: list[str] = []
    try:
        files_touched = sorted(agent.auto_agents.modified_files)
    except Exception:
        pass
    content = build_handoff(summary=summary, files_touched=files_touched, next_steps=[])
    path = save_handoff(content=content, session_id=agent.session_id, cwd=agent.cwd)
    return f"Saved handoff: {path}"


@slash_command("plan", "Plan artifact (save/list/load) — save|list|load [name]")
def cmd_plan_artifact(agent: AgentLoop, args: str) -> str:
    from .plans import list_plans, load_plan, save_plan

    tokens = args.split(None, 1)
    sub = tokens[0].lower() if tokens else "list"
    rest = tokens[1] if len(tokens) > 1 else ""

    if sub == "save":
        name_and_body = rest.split(None, 1)
        name = name_and_body[0] if name_and_body else None
        body = name_and_body[1] if len(name_and_body) > 1 else ""
        if not body:
            return "Usage: /plan save <name> <body>"
        path = save_plan(body, name=name, cwd=agent.cwd)
        return f"Saved plan: {path}"

    if sub == "load":
        if not rest:
            return "Usage: /plan load <name>"
        try:
            return load_plan(rest, cwd=agent.cwd)
        except FileNotFoundError as exc:
            return str(exc)

    if sub == "list":
        plans = list_plans(cwd=agent.cwd)
        if not plans:
            return "No plans yet. Use '/plan save <name> <body>' to create one."
        lines = ["Plans (newest first):"]
        for p in plans:
            lines.append(f"  {p.name}  ({p.size_chars} chars)")
        return "\n".join(lines)

    return "Usage: /plan [save <name> <body> | list | load <name>]"


@slash_command("bug", "Report a bug or issue")
def cmd_bug(agent: AgentLoop, args: str) -> str:
    import platform

    info = (
        f"HermitAgent v{VERSION}\n"
        f"Python {sys.version}\n"
        f"OS: {platform.platform()}\n"
        f"Model: {agent.llm.model}\n"
        f"Session: {agent.session_id}\n"
        f"Turns: {agent.turn_count}"
    )
    return f"Bug report info:\n{info}\n\nDescribe the issue and paste this info."


@slash_command("vim", "Open a file in vim/nano editor")
def cmd_vim(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "Usage: /vim <filepath>"
    filepath = args.strip()
    editor = os.environ.get("EDITOR", "vim")
    os.system(f"{editor} {filepath}")
    return f"Opened {filepath} in {editor}"


@slash_command("interview", "Start a deep interview to clarify requirements")
def cmd_interview(agent: AgentLoop, args: str) -> str:
    from .interview import DeepInterviewer, load_latest_interview

    if not args.strip():
        # Try to resume a previous interview
        state = load_latest_interview()
        if state and not state.is_complete:
            interviewer = DeepInterviewer(agent.llm, agent.cwd)
            question = interviewer.generate_question(state)
            progress = interviewer.format_progress(state)
            return f"Resuming interview ({state.interview_id})\n{progress}\n\nNext question:\n{question}"
        return "Usage: /interview <your idea or description>\nStarts a Socratic deep interview to clarify requirements before execution."

    idea = args.strip()
    from .interview import DeepInterviewer as _DI

    interviewer = _DI(agent.llm, agent.cwd)
    state = interviewer.start(idea)

    # First question is generated by the LLM agent via streaming (non-streaming call removed to prevent timeout)
    agent.messages.append(
        {
            "role": "user",
            "content": (
                f"You are conducting a deep interview to clarify requirements.\n"
                f'User\'s idea: "{idea}"\n'
                f"Project type: {state.project_type.value}\n"
                f"Interview ID: {state.interview_id}\n\n"
                "Start by asking the FIRST targeted question to clarify the user's requirements.\n"
                "Rules:\n"
                "1. Ask ONE question at a time — focus on the weakest clarity dimension\n"
                "2. Show ambiguity score after each answer (Goal/Constraints/Criteria 0-100%)\n"
                "3. Round 4+: challenge assumptions. Round 6+: simplify. Round 8+: find essence.\n"
                "4. When ambiguity ≤ 20%, generate a spec and offer execution options.\n\n"
                "Now ask your first question."
            ),
        }
    )
    return TRIGGER_AGENT_SINGLE


@slash_command("plugins", "List installed plugins")
def cmd_plugins(agent: AgentLoop, args: str) -> str:
    plugins = agent.plugin_registry.manager.list_plugins()
    if not plugins:
        return "No plugins installed. Add plugins in ~/.hermit/plugins/<name>/plugin.json"
    lines = ["Installed plugins:"]
    for p in plugins:
        status = "enabled" if p.enabled else "disabled"
        hooks = len(p.hooks_pre) + len(p.hooks_post)
        lines.append(f"  {p.name} v{p.version} [{status}] — {p.description} ({hooks} hooks)")
    return "\n".join(lines)


@slash_command("undo", "Undo unstaged changes (git checkout -- .)")
def cmd_undo(agent: AgentLoop, args: str) -> str:
    try:
        diff = subprocess.run(
            ["git", "diff", "--stat"],
            check=False,
            capture_output=True,
            text=True,
            cwd=agent.cwd,
            timeout=10,
        )
        diff_output = diff.stdout.strip()
        if not diff_output:
            return "No unstaged changes to undo."
        result = subprocess.run(
            ["git", "checkout", "--", "."],
            check=False,
            capture_output=True,
            text=True,
            cwd=agent.cwd,
            timeout=10,
        )
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return f"Undone changes:\n{diff_output}"
    except Exception as e:
        return f"Error: {e}"


@slash_command("status", "Show agent status: turns, tokens, modified files, error history")
def cmd_status(agent: AgentLoop, args: str) -> str:
    from .context import estimate_messages_tokens

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


@slash_command("plan", "Trigger the PlanAgent to create a plan")
def cmd_plan_generate(agent: AgentLoop, args: str) -> str:
    topic = args.strip() if args.strip() else "the current task"
    agent.messages.append(
        {
            "role": "user",
            "content": f"Create a detailed step-by-step plan for: {topic}. Break it into concrete, actionable steps. For each step, describe what needs to be done and why. Use numbered list format.",
        }
    )
    return TRIGGER_AGENT


@slash_command("search", "Search for a pattern in cwd using grep")
def cmd_search(agent: AgentLoop, args: str) -> str:
    pattern = args.strip()
    if not pattern:
        return "Usage: /search <pattern>"
    try:
        result = subprocess.run(
            ["rg", "--no-heading", "--line-number", "--max-count", "50", pattern, agent.cwd],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            # fallback to grep
            result2 = subprocess.run(
                ["grep", "-rn", pattern, agent.cwd],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result2.stdout.strip()
        return output[:5000] if output else f"No matches for: {pattern}"
    except FileNotFoundError:
        try:
            result = subprocess.run(
                ["grep", "-rn", pattern, agent.cwd],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout.strip()
            return output[:5000] if output else f"No matches for: {pattern}"
        except Exception as e:
            return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@slash_command("think", "Send a question to LLM for pure reasoning (no tools)")
def cmd_think(agent: AgentLoop, args: str) -> str:
    question = args.strip()
    if not question:
        return "Usage: /think <question>"
    try:
        response = agent.llm.chat(
            messages=[{"role": "user", "content": question}],
            system="You are a thoughtful reasoning assistant. Think carefully and thoroughly. No tool calls — pure reasoning only.",
            temperature=0.7,
        )
        return response.content or "[No response]"
    except Exception as e:
        return f"Error: {e}"


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


@slash_command("ralph", "Start persistence loop — keeps working until task is done")
def cmd_ralph(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "Usage: /ralph <task description>"

    agent._ran_ralph = True  # Enable keep-going resume flag
    from .ralph import Ralph, save_state

    # Auto model routing: switch to speed model (long code generation)
    prev_model = agent.llm.use_tier("speed")
    agent.emitter.model_changed(prev_model, agent.llm.model)

    ralph = Ralph(llm=agent.llm, tools=list(agent.tools.values()), cwd=agent.cwd, emitter=agent.emitter)
    setattr(ralph, "_parent_agent", agent)  # btw: for receiving user messages during execution
    state = ralph.start(args.strip())
    save_state(state)

    agent.messages.append(
        {
            "role": "user",
            "content": (
                f"[Ralph] Starting persistence loop for task: {args.strip()}\n"
                f"Task ID: {state.task_id}\n"
                f"Acceptance criteria ({len(state.acceptance_criteria)}):\n"
                + "\n".join(f"  {i + 1}. {c}" for i, c in enumerate(state.acceptance_criteria))
                + f"\n\nRunning up to {state.max_iterations} iterations until all criteria are met."
            ),
        }
    )

    # Run the loop synchronously (blocking)
    try:
        summary = ralph.run_loop(state)
    finally:
        agent.llm.restore_model(prev_model)
        agent.emitter.model_changed(agent.llm.model, prev_model)

    return f"[Ralph completed]\n{summary}"


@slash_command("cancel", "Cancel active execution mode (ralph, ultraqa, etc)")
def cmd_cancel(agent: AgentLoop, args: str) -> str:
    cancelled = []
    from .ralph import find_active_ralph
    from .ralph import save_state as ralph_save

    rs = find_active_ralph()
    if rs:
        rs.status = "cancelled"
        ralph_save(rs)
        cancelled.append(f"Ralph [{rs.task_id}]")
    from .autopilot import _save as ap_save
    from .autopilot import find_active_autopilot

    ap = find_active_autopilot()
    if ap:
        ap.status = "cancelled"
        ap.phase_log.append("cancelled")
        ap_save(ap)
        cancelled.append(f"Autopilot [{ap.task_id}] at phase {ap.phase.value}")
    try:
        from .ultraqa import find_active_ultraqa
        from .ultraqa import save_state as uqa_save

        uq = find_active_ultraqa()
        if uq:
            uq.status = "cancelled"
            uqa_save(uq)
            cancelled.append(f"UltraQA [{uq.task_id}]")
    except Exception:
        pass
    if cancelled:
        return "Cancelled:\n" + "\n".join(f"  - {c}" for c in cancelled)
    return "No active execution modes found."


@slash_command("autopilot", "Full autonomous pipeline — spec→plan→execute→QA→verify")
def cmd_autopilot(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "Usage: /autopilot <task description>"
    from .autopilot import Autopilot

    prev_model = agent.llm.use_tier("speed")
    agent.emitter.model_changed(prev_model, agent.llm.model)

    ap = Autopilot(agent.llm, agent.cwd, emitter=agent.emitter)
    state = ap.start(args.strip())
    try:
        summary = ap.run(state)
    finally:
        agent.llm.restore_model(prev_model)
        agent.emitter.model_changed(agent.llm.model, prev_model)

    return f"[Autopilot completed]\n{summary}"


@slash_command("test", "Trigger the test skill")
def cmd_test(agent: AgentLoop, args: str) -> str:
    from .skills import SkillRegistry

    registry = SkillRegistry()
    skill = registry.get("test")
    if skill:
        agent.messages.append(
            {
                "role": "user",
                "content": f"Execute the following skill:\n\n{skill.content}",
            }
        )
        return TRIGGER_AGENT
    # Fallback: ask the agent to run tests
    agent.messages.append(
        {
            "role": "user",
            "content": "Run the project's tests. Discover the test runner (pytest, npm test, etc.), execute the tests, and report results including any failures.",
        }
    )
    return TRIGGER_AGENT


@slash_command("mcp", "Show MCP server status")
def cmd_mcp(agent: AgentLoop, args: str) -> str:
    try:
        from .mcp import MCPManager

        mcp = MCPManager()
        servers = mcp.status()
        if not servers:
            return (
                "No MCP servers configured.\n"
                "Edit ~/.hermit/mcp.json to add servers.\n\n"
                'Example:\n  {"servers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}}}'
            )
        lines = ["MCP Servers:"]
        for s in servers:
            status = "[connected]" if s["connected"] else "[disconnected]"
            lines.append(f"  {status} {s['name']} — {s['command']} ({s['tools']} tools)")
        return "\n".join(lines)
    except Exception as e:
        return f"MCP error: {e}"


@slash_command("doctor", "Check environment and configuration")
def cmd_doctor_env(agent: AgentLoop, args: str) -> str:
    checks = []
    # LLM connectivity check
    try:
        import requests

        requests.get(f"{agent.llm.base_url}/models", timeout=5).raise_for_status()
        checks.append("[OK] LLM server reachable")
    except Exception:
        checks.append("[FAIL] LLM server not reachable")
    # Git check
    try:
        r = subprocess.run(["git", "status"], check=False, capture_output=True, cwd=agent.cwd, timeout=5)
        checks.append("[OK] Git repository" if r.returncode == 0 else "[WARN] Not a git repo")
    except Exception:
        checks.append("[WARN] Git not available")
    # ripgrep check
    try:
        subprocess.run(["rg", "--version"], check=False, capture_output=True, timeout=5)
        checks.append("[OK] ripgrep available")
    except FileNotFoundError:
        checks.append("[WARN] ripgrep not found (grep fallback)")
    # Memory directory
    mem_dir = os.path.expanduser("~/.hermit/memory")
    checks.append(f"[OK] Memory dir: {mem_dir}" if os.path.isdir(mem_dir) else "[INFO] Memory dir not yet created")
    return "\n".join(checks)


@slash_command("ultraqa", "Start QA cycling — test→diagnose→fix→repeat until pass")
def cmd_ultraqa(agent: AgentLoop, args: str) -> str:
    from .ultraqa import UltraQA

    test_command = args.strip() or None
    qa = UltraQA(llm=agent.llm, tools=list(agent.tools.values()), cwd=agent.cwd, emitter=agent.emitter)
    state = qa.start(test_command)

    agent.emitter.progress(f"[UltraQA] Starting — command: {state.test_command} | max cycles: {state.max_cycles}")

    summary = qa.run_loop(state)

    return f"[UltraQA completed]\n{summary}"


@slash_command("consensus", "Run consensus planning (Planner→Architect→Critic)")
def cmd_consensus(agent: AgentLoop, args: str) -> str:
    task = args.strip()
    if not task:
        return "Usage: /consensus <task description>"

    from .auto_agents import run_plan_consensus

    agent.emitter.progress(f"[Consensus] Starting for: {task[:60]}")
    result = run_plan_consensus(llm=agent.llm, cwd=agent.cwd, task=task)

    return f"[Consensus plan ready]\n{result}"


@slash_command("terminal-setup", "Show terminal configuration tips")
def cmd_terminal_setup(agent: AgentLoop, args: str) -> str:
    return f"""Terminal setup for best HermitAgent experience:
  - Use a terminal that supports 256 colors (iTerm2, Wezterm, Alacritty)
  - Font: any Nerd Font for icon support
  - Min width: 80 columns recommended
  - Shell: zsh or bash
  - Current terminal: {os.get_terminal_size().columns}x{os.get_terminal_size().lines}"""


@slash_command("pr-comments", "Show GitHub PR comments")
def cmd_pr_comments(agent: AgentLoop, args: str) -> str:
    pr_num = args.strip()
    if not pr_num:
        return "Usage: /pr-comments <PR_NUMBER>"
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_num, "--comments", "--json", "comments"],
            check=False,
            capture_output=True,
            text=True,
            cwd=agent.cwd,
            timeout=15,
        )
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()[:5000] or "No comments."
    except FileNotFoundError:
        return "GitHub CLI (gh) not found. Install with: brew install gh"
    except Exception as e:
        return f"Error: {e}"


@slash_command("permissions", "Show or change permission mode")
def cmd_permissions(agent: AgentLoop, args: str) -> str:
    from .permissions import PermissionMode

    if args.strip():
        try:
            new_mode = PermissionMode(args.strip())
            agent.permission_checker.mode = new_mode
            return f"Permission mode changed to: {new_mode.value}"
        except ValueError:
            pass
    modes = [m.value for m in PermissionMode]
    return f"Current: {agent.permission_checker.mode.value}\nAvailable: {', '.join(modes)}\nUsage: /permissions <mode>"


@slash_command("learn", "Extract a reusable skill from this conversation. Use 'reset' to clear auto-learned skills.")
def cmd_learn(agent: AgentLoop, args: str) -> str:
    from pathlib import Path
    from .learner import Learner, AUTO_LEARNED_DIR
    import shutil

    if args.strip() == "reset":
        if os.path.exists(AUTO_LEARNED_DIR):
            count = len(list(Path(AUTO_LEARNED_DIR).glob("*.md")))
            shutil.rmtree(AUTO_LEARNED_DIR)
            os.makedirs(AUTO_LEARNED_DIR, exist_ok=True)
            return f"Reset {count} auto-learned skill(s). ({AUTO_LEARNED_DIR})"
        return "Auto-learned folder is empty."

    if args.strip() == "status":
        learner = Learner(agent.llm)
        return learner.status_report()

    tool_count = getattr(agent, "_tool_call_count", len(agent.messages))
    learner = Learner(agent.llm)
    result = learner.extract_from_success(agent.messages, tool_call_count=max(5, tool_count))
    if result:
        path = learner.save_auto_learned(result)
        if path:
            return f"Skill extracted: {result['name']}\n  {path}"
        return f"Skill extracted ({result['name']}) -- blocked by security scan, not saved."
    return "No reusable pattern found."


@slash_command("team", "Run tasks with coordinated parallel agents")
def cmd_team(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "Usage: /team <task1> && <task2> && ..."
    tasks = [t.strip() for t in args.split("&&") if t.strip()]
    if len(tasks) < 2:
        return "Need at least 2 tasks separated by &&"

    from .coordinator import run_parallel_agents

    task_dicts = [{"description": f"Task {i + 1}", "prompt": t} for i, t in enumerate(tasks)]
    result = run_parallel_agents(task_dicts, agent.llm, agent.cwd)
    return f"[Team completed]\n{result.summary}"


@slash_command("research", "Deep research — search multiple sources and cross-verify")
def cmd_research(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "Usage: /research <topic>"
    # Use deep_search tool via agent
    agent.messages.append(
        {
            "role": "user",
            "content": f"Research this topic thoroughly using deep_search. Search for multiple perspectives, cross-verify facts, and cite sources:\n\n{args.strip()}",
        }
    )
    return TRIGGER_AGENT


@slash_command("worktree", "Create git worktree for isolated work")
def cmd_worktree(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "Usage: /worktree <branch-name>\nCreates a git worktree for isolated development."
    branch = args.strip()
    worktree_path = os.path.join(agent.cwd, "..", f"worktree-{branch}")
    try:
        result = subprocess.run(
            ["git", "worktree", "add", worktree_path, "-b", branch],
            check=False,
            capture_output=True,
            text=True,
            cwd=agent.cwd,
            timeout=15,
        )
        if result.returncode == 0:
            return f"Worktree created: {worktree_path}\nBranch: {branch}\nSwitch with: /model (then work in that directory)"
        return f"Error: {result.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"


@slash_command("hud", "Configure status bar display")
def cmd_hud(agent: AgentLoop, args: str) -> str:
    if not args.strip():
        return "HUD presets:\n  /hud minimal — model + ctx only\n  /hud full — all info\n  /hud off — hide status bar"
    preset = args.strip().lower()
    # Store preference in memory
    from .memory import MemorySystem

    mem = MemorySystem()
    mem.save("hud_preset", f"HUD preset: {preset}", "feedback", f"User prefers {preset} HUD")
    return f"HUD preset set to: {preset} (applied next session)"


@slash_command("deepinit", "Auto-generate AGENTS.md for each directory")
def cmd_deepinit(agent: AgentLoop, args: str) -> str:
    from .deepinit import generate_agents_md

    created = generate_agents_md(agent.cwd, agent.llm)
    if created:
        return f"Generated {len(created)} AGENTS.md files:\n" + "\n".join(f"  - {p}" for p in created)
    return "No directories need AGENTS.md (all already documented or no source files)."


def handle_slash_command(agent: AgentLoop, input_text: str) -> str | None:
    """Handle slash commands.

    Return values:
    - str: output directly
    - TRIGGER_AGENT: trigger agent execution (message already added)
    - None: not a slash command
    """
    if not input_text.startswith("/"):
        return None

    parts = input_text[1:].split(None, 1)
    cmd_name = parts[0].lower()
    cmd_args = parts[1] if len(parts) > 1 else ""

    # Built-in commands
    if cmd_name in SLASH_COMMANDS:
        return SLASH_COMMANDS[cmd_name]["func"](agent, cmd_args)

    # Execute directly by skill/command name
    from .skills import SkillRegistry

    registry = SkillRegistry()
    skill = registry.get(cmd_name)
    if skill:
        # Claude Code's substituteArguments() pattern: $ARGUMENTS, $0, $ARGUMENTS[n] substitution
        from .skills import adapt_for_hermit_agent, substitute_arguments

        skill_content = adapt_for_hermit_agent(substitute_arguments(skill.content, cmd_args))
        args_section = f"\nArguments: {cmd_args}" if cmd_args.strip() else ""
        # Auto-load .md files referenced within the skill (Claude Code pattern)
        resolved_refs = _resolve_skill_references(skill_content)
        if resolved_refs:
            skill_content += "\n\n--- Referenced Skills ---\n" + resolved_refs
        # If the skill has interview/interactive steps, instruct to wait for user input
        interactive_hint = ""
        if any(kw in skill_content.lower() for kw in ["interview", "ask the user"]):
            interactive_hint = "IMPORTANT: When the skill requires an interview or user input, you MUST stop and ask the user questions. Wait for their response before proceeding to the next phase.\n"

        # Load rules (global + project `.hermit/rules/`)
        rules_section = _load_rules(cwd=agent.cwd)

        # SDD task state initialization -- create task_state.md at skill start
        _write_task_state(agent.cwd, cmd_name, cmd_args, skill_content)
        agent._skill_active = True  # Enable auto-continue

        # KB domain knowledge injection (matching skill-related keywords)
        kb_section = ""
        try:
            from .kb_learner import KBLearner

            kb = KBLearner(cwd=agent.cwd)
            context_keywords = [w for w in (cmd_args + " " + cmd_name).split() if len(w) > 2]
            kb_content = kb.format_for_injection(context_keywords or None)
            if kb_content:
                kb_section = f"--- Domain Knowledge (KB) ---\n{kb_content}\n\n"
        except Exception:
            pass

        agent.messages.append(
            {
                "role": "user",
                "content": (
                    f"Execute this skill NOW. Do NOT explain — start executing immediately using tools (bash, read_file, edit_file, etc.).\n"
                    f"Follow the steps exactly as written. Do NOT run ls or explore first.\n"
                    f"{interactive_hint}"
                    f"Working directory: {agent.cwd}{args_section}\n\n"
                    f"IMPORTANT: A task state file has been created at `{agent.cwd}/.hermit/task_state.md`. "
                    f"Update this file as you complete each step (use edit_file). "
                    f"If context is compressed, re-read this file to restore your progress.\n\n"
                    f"{rules_section}"
                    f"--- Project Config ---\n{_find_project_config(agent.cwd)}\n\n"
                    f"{kb_section}"
                    f"--- Skill ---\n{skill_content}"
                ),
            }
        )
        return TRIGGER_AGENT

    return f"Unknown command: /{cmd_name}. Type /help for available commands."


# --- Output Helpers ----------------------------------------------------------


def _load_rules(cwd: str | None = None) -> str:
    """Load rule files. Claude Code pattern + project-local `.hermit/rules/`.

    Search order:
    1. `~/.hermit/rules/*.md` (HermitAgent global)
    2. `~/.claude/rules/*.md` (Claude Code global)
    3. `{cwd}/.hermit/rules/*.md` (project-specific -- only if cwd is given)

    Called from two sites with identical behavior:
    - line 2387: skill execution path (agent.cwd)
    - line 2525: slash command preprocessing (cwd)

    Related: _find_rules() at line 79 is a separate function that scans only
    .hermit/rules/ (used in _build_dynamic_context and post-compaction
    re-injection). The two functions serve different purposes and should
    not be merged.

    Behavior is characterized by tests/test_load_rules.py — any refactor
    must preserve the test suite outcomes.
    """
    from pathlib import Path

    dirs = [
        os.path.expanduser("~/.hermit/rules"),
        os.path.expanduser("~/.claude/rules"),
    ]
    if cwd:
        dirs.append(os.path.join(cwd, ".hermit", "rules"))

    sections = []
    for rules_dir in dirs:
        if not os.path.isdir(rules_dir):
            continue
        for f in sorted(Path(rules_dir).glob("*.md")):
            try:
                content = f.read_text()
                # Size limit (context protection)
                if len(content) > 3000:
                    content = content[:3000] + "\n[...truncated]"
                sections.append(f"# Rules: {f.name}\n{content}")
            except Exception:
                continue
    if sections:
        return "--- Rules ---\n" + "\n\n".join(sections) + "\n\n"
    return ""


def _resolve_skill_references(content: str) -> str:
    """Auto-load .md files referenced in skill content.

    Pattern: `~/.claude/commands/xxx.md` or `~/.hermit/commands/xxx.md`
    """
    import re

    ref_pattern = re.compile(r"`(~/.(?:claude|hermit_agent)/commands/[^`]+\.md)`")
    refs = ref_pattern.findall(content)
    if not refs:
        return ""

    sections = []
    seen = set()
    for ref_path in refs:
        expanded = os.path.expanduser(ref_path)
        if expanded in seen or not os.path.isfile(expanded):
            continue
        seen.add(expanded)
        try:
            with open(expanded) as f:
                ref_content = f.read()
            # Reference size limit (context protection)
            if len(ref_content) > 5000:
                ref_content = ref_content[:5000] + "\n[...truncated]"
            sections.append(f"## {os.path.basename(expanded)}\n{ref_content}")
        except Exception:
            continue
    return "\n\n".join(sections)


def _preprocess_slash_command(full_task: str, slash_line: str, cwd: str) -> str:
    """Convert /skill-name args slash commands to skill content in MCP/Gateway mode.

    Produces the same result as handle_slash_command() in CLI mode.
    full_task may include a learned_feedback block, which is preserved as a prefix.
    """
    from .skills import SkillRegistry, adapt_for_hermit_agent, substitute_arguments

    parts = slash_line[1:].split(None, 1)
    cmd_name = parts[0].lower()
    cmd_args = parts[1] if len(parts) > 1 else ""

    registry = SkillRegistry()
    skill = registry.get(cmd_name)
    if not skill:
        return full_task  # No skill found, pass through as-is

    skill_content = adapt_for_hermit_agent(substitute_arguments(skill.content, cmd_args))
    args_section = f"\nArguments: {cmd_args}" if cmd_args.strip() else ""
    resolved_refs = _resolve_skill_references(skill_content)
    if resolved_refs:
        skill_content += "\n\n--- Referenced Skills ---\n" + resolved_refs

    interactive_hint = ""
    if any(kw in skill_content.lower() for kw in ["interview", "ask the user"]):
        interactive_hint = "IMPORTANT: When the skill requires an interview or user input, you MUST stop and ask the user questions. Wait for their response before proceeding to the next phase.\n"

    rules_section = _load_rules(cwd=cwd)
    _write_task_state(cwd, cmd_name, cmd_args, skill_content)

    # Keep learned_feedback block as prefix, replace only the slash command part with skill content
    learned_prefix = ""
    if "<learned_feedback>" in full_task:
        learned_prefix = full_task.split("\n\n", 1)[0] + "\n\n"

    skill_message = (
        f"Execute this skill NOW. Do NOT explain -- start executing immediately using tools (bash, read_file, edit_file, etc.).\n"
        f"Follow the steps exactly as written. Do NOT run ls or explore first.\n"
        f"{interactive_hint}"
        f"Working directory: {cwd}{args_section}\n\n"
        f"IMPORTANT: A task state file has been created at `{cwd}/.hermit/task_state.md`. "
        f"Update this file as you complete each step (use edit_file). "
        f"If context is compressed, re-read this file to restore your progress.\n\n"
        f"{rules_section}"
        f"--- Project Config ---\n{_find_project_config(cwd)}\n\n"
        f"--- Skill ---\n{skill_content}"
    )
    return learned_prefix + skill_message


