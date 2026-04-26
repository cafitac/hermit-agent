"""Slash commands — dev group."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from ..version import VERSION
from ._registry import slash_command, TRIGGER_AGENT

if TYPE_CHECKING:
    from ..loop import AgentLoop

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


@slash_command("plan", "Plan artifact (save/list/load) — save|list|load [name]")
def cmd_plan_artifact(agent: AgentLoop, args: str) -> str:
    from ..plans import list_plans, load_plan, save_plan

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


@slash_command("test", "Trigger the test skill")
def cmd_test(agent: AgentLoop, args: str) -> str:
    from ..skills import SkillRegistry

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

