"""Slash commands — config group."""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from ._registry import slash_command

if TYPE_CHECKING:
    from ..loop import AgentLoop

@slash_command("model", "Show or change model")
def cmd_model(agent: AgentLoop, args: str) -> str:
    if args.strip():
        new_model = args.strip()
        agent.llm.model = new_model
        # Save as default model
        from ..memory import MemorySystem

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


@slash_command("skills", "List available skills")
def cmd_skills(agent: AgentLoop, args: str) -> str:
    from ..skills import SkillRegistry

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
    from ..doctor import run_diagnostics

    return run_diagnostics(cwd=agent.cwd).format()


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


@slash_command("terminal-setup", "Show terminal configuration tips")
def cmd_terminal_setup(agent: AgentLoop, args: str) -> str:
    return f"""Terminal setup for best HermitAgent experience:
  - Use a terminal that supports 256 colors (iTerm2, Wezterm, Alacritty)
  - Font: any Nerd Font for icon support
  - Min width: 80 columns recommended
  - Shell: zsh or bash
  - Current terminal: {os.get_terminal_size().columns}x{os.get_terminal_size().lines}"""


@slash_command("permissions", "Show or change permission mode")
def cmd_permissions(agent: AgentLoop, args: str) -> str:
    from ..permissions import PermissionMode

    if args.strip():
        try:
            new_mode = PermissionMode(args.strip())
            agent.permission_checker.mode = new_mode
            return f"Permission mode changed to: {new_mode.value}"
        except ValueError:
            pass
    modes = [m.value for m in PermissionMode]
    return f"Current: {agent.permission_checker.mode.value}\nAvailable: {', '.join(modes)}\nUsage: /permissions <mode>"


@slash_command("deepinit", "Auto-generate AGENTS.md for each directory")
def cmd_deepinit(agent: AgentLoop, args: str) -> str:
    from ..deepinit import generate_agents_md

    created = generate_agents_md(agent.cwd, agent.llm)
    if created:
        return f"Generated {len(created)} AGENTS.md files:\n" + "\n".join(f"  - {p}" for p in created)
    return "No directories need AGENTS.md (all already documented or no source files)."

