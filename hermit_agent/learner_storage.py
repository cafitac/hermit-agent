"""Storage helpers for learned skill metadata and markdown files."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SkillMeta:
    """Skill performance metadata."""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    status: str = "pending"
    created_at: str = ""
    last_used: str = ""
    use_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    missed_count: int = 0
    needs_review: bool = False
    verify_cmd: str = ""

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def to_frontmatter(self) -> str:
        triggers_yaml = json.dumps(self.triggers)
        scope_yaml = json.dumps(self.scope)
        return (
            f"name: {self.name}\n"
            f"description: {self.description}\n"
            f"type: learned-feedback\n"
            f"status: {self.status}\n"
            f"triggers: {triggers_yaml}\n"
            f"scope: {scope_yaml}\n"
            f"created_at: {self.created_at}\n"
            f"last_used: {self.last_used}\n"
            f"use_count: {self.use_count}\n"
            f"success_count: {self.success_count}\n"
            f"fail_count: {self.fail_count}\n"
            f"success_rate: {self.success_rate:.2f}\n"
            f"missed_count: {self.missed_count}\n"
            f"needs_review: {str(self.needs_review).lower()}\n"
            f"verify_cmd: {self.verify_cmd}\n"
        )

    @classmethod
    def from_frontmatter(cls, meta: dict) -> "SkillMeta":
        triggers = meta.get("triggers", [])
        if isinstance(triggers, str):
            try:
                triggers = json.loads(triggers)
            except Exception:
                triggers = [t.strip() for t in triggers.split(",") if t.strip()]
        scope = meta.get("scope", [])
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except Exception:
                scope = [s.strip() for s in scope.split(",") if s.strip()]
        needs_review_raw = meta.get("needs_review", "false")
        needs_review = needs_review_raw is True or str(needs_review_raw).lower() == "true"
        return cls(
            name=meta.get("name", ""),
            description=meta.get("description", ""),
            triggers=triggers,
            scope=scope,
            status=meta.get("status", "pending"),
            created_at=meta.get("created_at", ""),
            last_used=meta.get("last_used", ""),
            use_count=int(meta.get("use_count", 0)),
            success_count=int(meta.get("success_count", 0)),
            fail_count=int(meta.get("fail_count", 0)),
            missed_count=int(meta.get("missed_count", 0)),
            needs_review=needs_review,
            verify_cmd=meta.get("verify_cmd", ""),
        )


_VERIFY_RULES_PATH = os.path.expanduser("~/.hermit/skills/verify-rules.json")


def parse_skill_file(path: str) -> tuple[SkillMeta, str] | None:
    """Parse YAML frontmatter + body. Returns (meta, body)."""
    try:
        text = Path(path).read_text()
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        fm_str, body = match.groups()
        meta: dict = {}
        for line in fm_str.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        return SkillMeta.from_frontmatter(meta), body.strip()
    except Exception:
        return None


def write_skill_file(path: str, meta: SkillMeta, body: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(f"---\n{meta.to_frontmatter()}---\n\n{body}\n")


def current_day() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_verify_rules() -> dict:
    """Load verify-rules.json. Returns an empty dict if missing or parse fails."""
    try:
        with open(_VERIFY_RULES_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def add_hub_backlink(skill_path: str, hub_name: str) -> None:
    """Append a hub back-link to the bottom of a skill file. Skip if already present."""
    hub_labels = {
        "_hub_auto": "Auto-Learning Hub",
        "_hub_approved": "Approved Feedback",
        "_hub_feedback": "Manual Feedback",
        "_hub_skills": "Core Skills",
        "_hub_standards": "Code Standards",
    }
    link = f"[[{hub_name}|{hub_labels.get(hub_name, hub_name)}]]"
    try:
        content = Path(skill_path).read_text()
        if link in content:
            return
        Path(skill_path).write_text(content.rstrip() + f"\n\n---\n← {link}\n")
    except Exception:
        pass
