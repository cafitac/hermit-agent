"""Memory system — Persisting information across conversations.

Referencing Claude Code's memdir/ pattern:
- MEMORY.md index file + individual memory files
- frontmatter (YAML) + markdown body
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MEMORY_DIR = os.path.expanduser("~/.hermit/memory")
INDEX_FILE = "MEMORY.md"
MAX_INDEX_LINES = 200


@dataclass
class MemoryEntry:
    name: str
    description: str
    mem_type: str  # user, project, feedback, reference
    content: str
    filename: str


class MemorySystem:
    """File-based memory system.

    Structure:
      ~/.hermit/memory/
        MEMORY.md              ← Index (list of one-line summaries)
        user_role.md           ← Individual memory file
        project_auth_rewrite.md
        ...
"""

    def __init__(self, memory_dir: str = DEFAULT_MEMORY_DIR):
        self.memory_dir = memory_dir
        os.makedirs(memory_dir, exist_ok=True)

    def save(self, name: str, content: str, mem_type: str = "project", description: str = "") -> str:
        """Save memory. Overwrite if the same name exists."""
        filename = f"{mem_type}_{_sanitize(name)}.md"
        filepath = os.path.join(self.memory_dir, filename)
        real_filepath = os.path.realpath(filepath)
        if not real_filepath.startswith(os.path.realpath(self.memory_dir)):
            raise ValueError(f"Memory path traversal blocked: {filename}")

        desc = description or name
        file_content = f"""---
name: {name}
description: {desc}
type: {mem_type}
---

{content}
"""
        with open(filepath, "w") as f:
            f.write(file_content)

        self._update_index(name, filename, desc)
        return filepath

    def load(self, name: str) -> MemoryEntry | None:
        """Load memory by name."""
        for entry in self.list_all():
            if entry.name == name:
                return entry
        return None

    def list_all(self) -> list[MemoryEntry]:
        """Load all memory files."""
        entries = []
        for f in Path(self.memory_dir).glob("*.md"):
            if f.name == INDEX_FILE:
                continue
            try:
                raw = f.read_text()
                parsed = _parse_frontmatter(raw)
                if parsed:
                    entries.append(MemoryEntry(
                        name=parsed.get("name", f.stem),
                        description=parsed.get("description", ""),
                        mem_type=parsed.get("type", "project"),
                        content=parsed.get("body", ""),
                        filename=f.name,
                    ))
            except Exception:
                continue
        return entries

    def delete(self, name: str) -> bool:
        """Delete memory by name."""
        for entry in self.list_all():
            if entry.name == name:
                filepath = os.path.join(self.memory_dir, entry.filename)
                os.remove(filepath)
                self._rebuild_index()
                return True
        return False

    def get_index(self) -> str:
        """Return MEMORY.md index contents."""
        index_path = os.path.join(self.memory_dir, INDEX_FILE)
        if os.path.exists(index_path):
            return Path(index_path).read_text()
        return "(no memories saved yet)"

    def get_relevant_context(self, llm=None, query: str = "") -> str:
        """Memory context to inject into the system prompt.

        Claude Code's findRelevantMemories.ts pattern:
        - If LLM is available, judge relevance and select up to 5 items
        - If LLM is not available, return up to 5 items from the total
"""
        entries = self.list_all()
        if not entries:
            return ""

        # Judge relevance using LLM
        if llm and query and len(entries) > 5:
            entries = self._select_relevant(llm, entries, query)
        else:
            entries = entries[:5]

        lines = ["# Saved Memories"]
        for entry in entries:
            lines.append(f"\n## {entry.name} ({entry.mem_type})")
            lines.append(entry.content[:500])

        return "\n".join(lines)

    def _select_relevant(self, llm, entries: list[MemoryEntry], query: str) -> list[MemoryEntry]:
        """Select up to 5 relevant memories using LLM. Claude Code's sideQuery pattern."""
        try:
            descriptions = "\n".join(
                f"{i}. [{e.name}] ({e.mem_type}) {e.description}"
                for i, e in enumerate(entries)
            )
            prompt = (
                f"Given this context: {query[:200]}\n\n"
                f"Which of these memories are relevant? Return ONLY the numbers, comma-separated. Max 5.\n\n"
                f"{descriptions}"
            )
            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system="Return only comma-separated numbers. Nothing else.",
                temperature=0.0,
            )
            if response.content:
                import re
                nums = [int(n) for n in re.findall(r'\d+', response.content)]
                selected = [entries[n] for n in nums if 0 <= n < len(entries)]
                return selected[:5] if selected else entries[:5]
        except Exception:
            pass
        return entries[:5]

    def _update_index(self, name: str, filename: str, description: str):
        """Add/update entry in the MEMORY.md index."""
        index_path = os.path.join(self.memory_dir, INDEX_FILE)
        lines: list[str] = []

        if os.path.exists(index_path):
            lines = Path(index_path).read_text().splitlines()

        # Remove existing entry
        lines = [line for line in lines if f"({filename})" not in line and f"[{name}]" not in line]

        # Add new entry
        lines.append(f"- [{name}]({filename}) — {description}")

        # Limit maximum number of lines
        if len(lines) > MAX_INDEX_LINES:
            lines = lines[-MAX_INDEX_LINES:]

        with open(index_path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def _rebuild_index(self):
        """Rebuild the entire index file."""
        entries = self.list_all()
        index_path = os.path.join(self.memory_dir, INDEX_FILE)
        lines = []
        for entry in entries:
            lines.append(f"- [{entry.name}]({entry.filename}) — {entry.description}")
        with open(index_path, "w") as f:
            f.write("\n".join(lines) + "\n")


def _sanitize(name: str) -> str:
    """Convert to a filename-safe string."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower().replace(" ", "_"))[:50]


def _parse_frontmatter(text: str) -> dict | None:
    """Parse YAML frontmatter + body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return None

    frontmatter_str, body = match.groups()
    result: dict = {"body": body.strip()}

    for line in frontmatter_str.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()

    return result
