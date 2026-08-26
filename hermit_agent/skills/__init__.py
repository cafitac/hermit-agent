"""Skill system — based on Claude Code's skills/loadSkillsDir.ts + bundledSkills.ts patterns.

Reusable workflows defined in SKILL.md files.
Users define skills under ~/.hermit/skills/ and invoke them with the /skill command.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SKILLS_DIR = os.path.expanduser("~/.hermit/skills")
DEFAULT_COMMANDS_DIR = os.path.expanduser("~/.hermit/commands")
PROJECT_SKILLS_DIR = ".hermit/skills"
PROJECT_COMMANDS_DIR = ".hermit/commands"

# CRITICAL: 패키지 내부 경로는 __file__ 기반 절대경로로 해석
# __file__ == hermit_agent/skills/__init__.py → dirname == hermit_agent/skills/
BUNDLED_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))

# Claude Code compatible paths (Claude Code's getSkillsPath pattern)
CLAUDE_SKILLS_DIR = os.path.expanduser("~/.claude/skills")
CLAUDE_COMMANDS_DIR = os.path.expanduser("~/.claude/commands")
CLAUDE_PROJECT_SKILLS_DIR = ".claude/skills"
CLAUDE_PROJECT_COMMANDS_DIR = ".claude/commands"


def _get_omc_plugin_skills_dirs() -> list[str]:
    """Search for oh-my-claudecode plugin skill directories.
    Claude Code plugin source pattern: ~/.claude/plugins/cache/omc/oh-my-claudecode/{version}/skills/
    """
    base = Path(os.path.expanduser("~/.claude/plugins/cache/omc/oh-my-claudecode"))
    if not base.exists():
        return []
    dirs = []
    for version_dir in sorted(base.iterdir(), reverse=True):  # latest version first
        skills_dir = version_dir / "skills"
        if skills_dir.is_dir():
            dirs.append(str(skills_dir))
            break  # only the latest version
    return dirs


@dataclass
class Skill:
    name: str
    description: str
    content: str  # body to be injected into the system prompt
    source: str  # "user", "project", "bundled"
    allowed_tools: list[str] | None = None  # None = all tools allowed
    model: str | None = None  # model override
    audience: list[str] | None = None  # None = allow all (backwards compat). e.g. ["hermit_agent"], ["claude-code"], ["both"].


def _audience_includes_hermit_agent(audience: list[str] | None) -> bool:
    """Determine whether the audience field targets a skill this HermitAgent loader should load."""
    if audience is None:
        return True
    lowered = {a.lower() for a in audience}
    return bool(lowered & {"hermit_agent", "both", "all"})


class SkillRegistry:
    """Skill registry.

    Directory structure:
      ~/.hermit/skills/
        deploy/
          SKILL.md
        review/
          SKILL.md
    """

    def __init__(self):
        self.skills: dict[str, Skill] = {}
        self._load_bundled()
        # git-shipped bundled skills (hermit_agent/skills/) — lower priority than user skills
        self._load_from_dir(BUNDLED_SKILLS_DIR, "bundled")
        # omc plugin skills (latest version, lower priority)
        for omc_dir in _get_omc_plugin_skills_dirs():
            self._load_from_dir(omc_dir, "plugin")
        # Claude Code compatible paths (~/.claude/)
        self._load_from_dir(CLAUDE_SKILLS_DIR, "user")
        self._load_from_dir(CLAUDE_PROJECT_SKILLS_DIR, "project")
        self._load_commands(CLAUDE_COMMANDS_DIR, "user-command")
        self._load_commands(CLAUDE_PROJECT_COMMANDS_DIR, "project-command")
        # hermit_agent dedicated paths (higher priority — loaded later, overwrites)
        self._load_from_dir(DEFAULT_SKILLS_DIR, "user")
        self._load_from_dir(PROJECT_SKILLS_DIR, "project")
        self._load_commands(DEFAULT_COMMANDS_DIR, "user-command")
        self._load_commands(PROJECT_COMMANDS_DIR, "project-command")

    def _load_bundled(self):
        """Register built-in skills."""
        self.skills["commit"] = Skill(
            name="commit",
            description="Create a git commit with a descriptive message",
            content="""Create a git commit for the current changes.

Steps:
1. Run `git status` to see changes
2. Run `git diff --staged` (or `git diff` if nothing staged) to review
3. Stage relevant files with `git add`
4. Write a concise commit message that describes the "why" not the "what"
5. Run `git commit -m "message"`
6. Show the result with `git log --oneline -1`

Commit message style: imperative mood, max 72 chars first line.""",
            source="bundled",
        )

        self.skills["review"] = Skill(
            name="review",
            description="Review code changes and suggest improvements",
            content="""Review the current code changes.

Steps:
1. Run `git diff` to see all changes
2. For each changed file, analyze:
   - Logic correctness
   - Error handling
   - Edge cases
   - Code style consistency
3. Provide feedback as:
   - P1 (must fix): bugs, security issues
   - P2 (should fix): design issues, missing error handling
   - P3 (nice to have): style, naming

Be specific. Reference file:line_number.""",
            source="bundled",
        )

        self.skills["test"] = Skill(
            name="test",
            description="Run tests and analyze results",
            content="""Run the project's test suite and analyze results.

Steps:
1. Find the test runner (pytest, npm test, cargo test, etc.)
2. Run the tests
3. If tests fail, analyze the failures
4. Suggest fixes for failing tests

Look for: pytest.ini, setup.cfg, package.json, Cargo.toml, Makefile.""",
            source="bundled",
        )

        self.skills["slop-clean"] = Skill(
            name="slop-clean",
            description="Clean AI-generated code slop — remove unnecessary wrappers, dead code, over-abstractions",
            content="""Clean AI-generated code slop in this project.

Steps:
1. Run `git diff` to see recent changes
2. For each changed file, look for:
   - Unnecessary wrapper functions (function that just calls another function)
   - Dead code (unused variables, unreachable branches, commented-out code)
   - Over-abstractions (interfaces with single implementation, unnecessary factory patterns)
   - Redundant error handling (try/except that just re-raises)
   - Unnecessary type annotations on obvious types
3. Delete the slop. Prefer deletion over refactoring.
4. Run tests after each deletion to verify nothing breaks.
5. Report what was cleaned.""",
            source="bundled",
        )

    def _load_from_dir(self, skills_dir: str, source: str):
        """Load SKILL.md files from a directory."""
        if not os.path.exists(skills_dir):
            return

        for entry in Path(skills_dir).iterdir():
            if not entry.is_dir():
                continue

            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                raw = skill_md.read_text()
                parsed = _parse_skill(raw)
                if parsed and _audience_includes_hermit_agent(parsed.audience):
                    parsed.source = source
                    self.skills[parsed.name] = parsed
            except Exception:
                continue

    def _load_commands(self, commands_dir: str, source: str):
        """Load .md command files from a directory as skills. Compatible with Claude Code's ~/.claude/commands/."""
        if not os.path.exists(commands_dir):
            return

        for entry in Path(commands_dir).iterdir():
            if not entry.is_file() or not entry.name.endswith(".md"):
                continue

            try:
                raw = entry.read_text()
                name = entry.stem  # code-polish-debate.md → code-polish-debate
                # Use the first line as the description
                first_line = ""
                for line in raw.splitlines():
                    stripped = line.strip().lstrip("#").strip()
                    if stripped:
                        first_line = stripped[:80]
                        break
                self.skills[name] = Skill(
                    name=name,
                    description=first_line or f"Command: {name}",
                    content=raw,
                    source=source,
                )
            except Exception:
                continue

    def register(self, skill: Skill) -> None:
        """Register a skill at runtime."""
        self.skills[skill.name] = skill

    def unregister(self, name: str) -> bool:
        """Unregister a skill."""
        return self.skills.pop(name, None) is not None

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def list_skills(self) -> list[Skill]:
        return sorted(self.skills.values(), key=lambda s: s.name)


def _parse_skill(text: str) -> Skill | None:
    """Parse SKILL.md (YAML frontmatter + markdown body)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        # No frontmatter — treat entire content as body
        return None

    frontmatter_str, body = match.groups()
    meta: dict[str, str] = {}
    for line in frontmatter_str.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    name = meta.get("name", "")
    if not name:
        return None

    allowed_tools = None
    if "allowed_tools" in meta:
        allowed_tools = [t.strip() for t in meta["allowed_tools"].split(",")]

    audience = None
    if "audience" in meta:
        audience = [a.strip() for a in meta["audience"].split(",") if a.strip()]

    return Skill(
        name=name,
        description=meta.get("description", name),
        content=body.strip(),
        source="",
        allowed_tools=allowed_tools,
        model=meta.get("model"),
        audience=audience,
    )


_HERMIT_TOOL_SUBS: list[tuple[str, str]] = [
    # Skill("oh-my-claudecode:X") → run_skill(name="X")
    (r'Skill\s*\(\s*"oh-my-claudecode:([^"]+)"\s*\)', r'run_skill(name="\1")'),
    # Skill("X") → run_skill(name="X")
    (r'Skill\s*\(\s*"([^"]+)"\s*\)', r'run_skill(name="\1")'),
    # AskUserQuestion → ask_user_question
    (r'\bAskUserQuestion\b', 'ask_user_question'),
    # `Write` tool → `write_file` tool  (spec/file save)
    (r'`Write` tool', '`write_file` tool'),
    # state_write / state_read → implemented under the same name in HermitAgent (no change needed)
]


def adapt_for_hermit_agent(content: str) -> str:
    """Substitute Claude Code-specific tool names with HermitAgent tool names.

    Applied at runtime while keeping symlinked skills intact.
    """
    for pattern, replacement in _HERMIT_TOOL_SUBS:
        content = re.sub(pattern, replacement, content)
    return content


def substitute_arguments(content: str, args: str) -> str:
    """Claude Code's substituteArguments() pattern.

    Substitution rules:
    - $ARGUMENTS       → full argument string
    - $ARGUMENTS[n]    → n-th argument (0-indexed, space-delimited)
    - $0, $1, ...      → shorthand form (n-th argument)
    - No placeholder   → appends 'ARGUMENTS: {args}' at the end
    """
    if not args or not args.strip():
        return content

    parsed = args.split()
    original = content

    # Substitute $ARGUMENTS[n]
    def replace_indexed(m: re.Match) -> str:
        idx = int(m.group(1))
        return parsed[idx] if idx < len(parsed) else ""

    content = re.sub(r"\$ARGUMENTS\[(\d+)\]", replace_indexed, content)

    # Substitute $0, $1, ... shorthand form (check word boundary)
    def replace_positional(m: re.Match) -> str:
        idx = int(m.group(1))
        return parsed[idx] if idx < len(parsed) else ""

    content = re.sub(r"\$(\d+)(?!\w)", replace_positional, content)

    # Substitute full $ARGUMENTS
    content = content.replace("$ARGUMENTS", args)

    # If no placeholder was found, append at the end
    if content == original:
        content = content + f"\n\nARGUMENTS: {args}"

    return content


def create_default_skills_dir():
    """Create the default skills directory if it does not exist."""
    os.makedirs(DEFAULT_SKILLS_DIR, exist_ok=True)
