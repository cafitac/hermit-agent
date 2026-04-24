"""KB Learner — automatic collection, validation, and deprecation of per-project domain knowledge.

Accumulates domain knowledge in the project directory under .hermit/kb/.
Facts discovered during HermitAgent tasks are organized automatically,
and outdated or incorrect information is cleaned up automatically.

Directory structure:
  .hermit/kb/
    wiki/        ← validated knowledge (injected into context)
      index.md
      {domain}/
        {topic}.md
    pending/     ← awaiting validation (not injected)
    deprecated/  ← deprecated knowledge (kept for reference)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

WIKI_ROOT = "kb/wiki"                 # project root. git tracked. team-shared.
LOCAL_ROOT = ".hermit/kb"            # local only. .gitignore.
PENDING_DIR = "pending"               # under LOCAL_ROOT
DEPRECATED_DIR = "deprecated"         # under LOCAL_ROOT
META_FILE = "meta.json"               # LOCAL_ROOT/meta.json — recurrence counter
INDEX_FILE = "index.md"               # WIKI_ROOT/index.md

DEFAULT_TTL_DAYS = 90       # mark as needing re-validation after this many days
MIN_CONFIDENCE = 0.5        # demote to pending if below this
AUTO_DEPRECATE_DAYS = 180   # auto-deprecate if unvalidated for this many days


# ---------------------------------------------------------------------------
# metadata schema
# ---------------------------------------------------------------------------

@dataclass
class KBPage:
    """KB page metadata + body."""
    title: str
    domain: str                        # domain (e.g. asset_company, payment)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    last_verified: str = ""
    verified_by: str = "agent"         # agent | pytest | human
    confidence: float = 0.8
    ttl_days: int = DEFAULT_TTL_DAYS
    version: int = 1
    status: str = "pending"            # pending | active | stale | deprecated
    body: str = ""

    @property
    def is_stale(self) -> bool:
        if not self.last_verified:
            return True
        try:
            last = datetime.strptime(self.last_verified, "%Y-%m-%d")
            return (datetime.now() - last).days > self.ttl_days
        except Exception:
            return True

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9_-]", "_", self.title.lower().replace(" ", "_"))

    def to_frontmatter(self) -> str:
        tags_yaml = json.dumps(self.tags, ensure_ascii=False)
        return (
            f"title: {self.title}\n"
            f"domain: {self.domain}\n"
            f"tags: {tags_yaml}\n"
            f"status: {self.status}\n"
            f"created_at: {self.created_at}\n"
            f"last_verified: {self.last_verified}\n"
            f"verified_by: {self.verified_by}\n"
            f"confidence: {self.confidence:.2f}\n"
            f"ttl_days: {self.ttl_days}\n"
            f"version: {self.version}\n"
        )

    @classmethod
    def from_frontmatter(cls, meta: dict, body: str = "") -> "KBPage":
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [t.strip() for t in tags.split(",") if t.strip()]
        return cls(
            title=meta.get("title", ""),
            domain=meta.get("domain", "general"),
            tags=tags,
            created_at=meta.get("created_at", ""),
            last_verified=meta.get("last_verified", ""),
            verified_by=meta.get("verified_by", "agent"),
            confidence=float(meta.get("confidence", 0.8)),
            ttl_days=int(meta.get("ttl_days", DEFAULT_TTL_DAYS)),
            version=int(meta.get("version", 1)),
            status=meta.get("status", "pending"),
            body=body,
        )


# ---------------------------------------------------------------------------
# file I/O helpers
# ---------------------------------------------------------------------------

def _parse_kb_file(path: str) -> KBPage | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        fm_str, body = match.groups()
        meta: dict = {}
        for line in fm_str.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        return KBPage.from_frontmatter(meta, body.strip())
    except Exception:
        return None


def _write_kb_file(path: str, page: KBPage) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        f"---\n{page.to_frontmatter()}---\n\n{page.body}\n",
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# core class
# ---------------------------------------------------------------------------

class KBLearner:
    """Project KB manager.

    Usage:
        kb = KBLearner(cwd="/project")
        # for context injection
        pages = kb.get_relevant_pages(keywords=["kiwoom", "sign_up"])
        # extract knowledge after a task
        kb.extract_and_save(messages, pytest_passed=True)
        # periodic cleanup
        kb.cleanup()
    """

    def __init__(self, cwd: str, llm=None):
        self.cwd = cwd
        self.llm = llm
        # Shared (git tracked, team wide)
        self.wiki_dir = os.path.join(cwd, WIKI_ROOT)
        # Local only (added to .gitignore)
        self.local_root = os.path.join(cwd, LOCAL_ROOT)
        self.pending_dir = os.path.join(self.local_root, PENDING_DIR)
        self.deprecated_dir = os.path.join(self.local_root, DEPRECATED_DIR)
        self.meta_path = os.path.join(self.local_root, META_FILE)
        for d in (self.wiki_dir, self.pending_dir, self.deprecated_dir):
            os.makedirs(d, exist_ok=True)
        # backward compatibility (for existing code references — functionally same as self.local_root)
        self.kb_root = self.local_root

    # ------------------------------------------------------------------
    # queries for context injection
    # ------------------------------------------------------------------

    def get_relevant_pages(self, keywords: list[str] | None = None, max_pages: int = 5) -> list[KBPage]:
        """Return wiki pages matching the given keywords (for context injection)."""
        pages: list[KBPage] = []
        for p in Path(self.wiki_dir).rglob("*.md"):
            if p.name == INDEX_FILE:
                continue
            page = _parse_kb_file(str(p))
            if not page or page.status == "deprecated":
                continue

            if keywords:
                search_text = " ".join([page.title, page.domain] + page.tags + [page.body[:200]])
                if not any(kw.lower() in search_text.lower() for kw in keywords):
                    continue

            pages.append(page)

        # sort by descending confidence, then most recently verified
        pages.sort(key=lambda p: (-p.confidence, p.last_verified or ""), reverse=False)
        return pages[:max_pages]

    def format_for_injection(self, keywords: list[str] | None = None) -> str:
        """Generate a string for context injection."""
        pages = self.get_relevant_pages(keywords)
        if not pages:
            return ""
        lines = ["## Project Domain Knowledge (KB)"]
        for page in pages:
            stale_mark = " ⚠️ (stale)" if page.is_stale else ""
            lines.append(f"\n### {page.title}{stale_mark}")
            lines.append(page.body[:1000])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # knowledge extraction (LLM-based)
    # ------------------------------------------------------------------

    def extract_from_conversation(
        self,
        messages: list[dict],
        pytest_passed: bool = False,
    ) -> list[dict]:
        """Extract domain knowledge from a conversation and test results."""
        if not self.llm:
            return []

        conversation = "\n".join(
            f"{m['role'].upper()}: {str(m.get('content', ''))[:500]}"
            for m in messages[-20:]  # last 20 turns
            if isinstance(m.get("content"), str)
        )

        prompt = f"""You are analyzing a coding agent's conversation to extract domain knowledge.

Conversation (recent):
{conversation}

Test result: {"PASSED" if pytest_passed else "FAILED"}

Extract domain knowledge facts discovered in this conversation.
Only extract facts about the BUSINESS DOMAIN (not code patterns — those go to learned-feedback skills).

Examples of domain knowledge:
- "Users in REJECTED status can be soft-deleted and re-register"
- "Kiwoom Capital delivery sign-up requires a SupportedMarket record"
- "AssetCompanyUser.registration_status uses the AssetCompanySignUpStatus enum"

For each fact, respond as JSON array:
[
  {{
    "title": "short title",
    "domain": "domain_name (e.g. asset_company, payment, user)",
    "tags": ["keyword1", "keyword2"],
    "confidence": 0.0-1.0,
    "fact": "clear statement of the fact"
  }}
]

If no domain knowledge was discovered, respond: []"""

        try:
            response = self.llm.chat([{"role": "user", "content": prompt}])
            text = response.content.strip() if hasattr(response, "content") else str(response).strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(text)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # pending storage
    # ------------------------------------------------------------------

    def save_pending(self, fact: dict) -> str | None:
        """Save an extracted fact to pending."""
        title = fact.get("title", "")
        if not title:
            return None

        page = KBPage(
            title=title,
            domain=fact.get("domain", "general"),
            tags=fact.get("tags", []),
            confidence=float(fact.get("confidence", 0.8)),
            created_at=_now(),
            last_verified=_now(),
            status="pending",
            body=f"## Content\n\n{fact.get('fact', '')}\n",
        )

        slug = page.slug
        path = os.path.join(self.pending_dir, f"{slug}.md")

        # detect conflict if the same title already exists in wiki
        existing = self._find_existing(title)
        if existing:
            self._handle_conflict(existing, page)
            return None

        _write_kb_file(path, page)
        # update recurrence counter (only when no conflict)
        self._bump_recurrence(slug)
        if self._get_recurrence(slug) >= 3:
            # auto-promote (appeared 3 times)
            promoted = self.promote_pending(slug, verified_by="recurrence")
            if promoted:
                self._reset_recurrence(slug)
        return path

    # ------------------------------------------------------------------
    # recurrence counter (meta.json)
    # ------------------------------------------------------------------

    def _load_meta(self) -> dict:
        try:
            with open(self.meta_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_meta(self, data: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self.meta_path), exist_ok=True)
            with open(self.meta_path, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _bump_recurrence(self, slug: str) -> None:
        meta = self._load_meta()
        rec = meta.setdefault("pending_recurrence", {})
        rec[slug] = rec.get(slug, 0) + 1
        self._save_meta(meta)

    def _get_recurrence(self, slug: str) -> int:
        meta = self._load_meta()
        return int(meta.get("pending_recurrence", {}).get(slug, 0))

    def _reset_recurrence(self, slug: str) -> None:
        meta = self._load_meta()
        rec = meta.get("pending_recurrence", {})
        if slug in rec:
            del rec[slug]
            self._save_meta(meta)

    def _find_existing(self, title: str) -> KBPage | None:
        """Search wiki for a page with the same title."""
        for p in Path(self.wiki_dir).rglob("*.md"):
            page = _parse_kb_file(str(p))
            if page and page.title == title:
                return page
        return None

    def _handle_conflict(self, existing: KBPage, new: KBPage) -> None:
        """Handle conflict between an existing page and new information.

        If new confidence is higher, update the existing page.
        If lower, store the new information in pending/conflict/.
        """
        if new.confidence > existing.confidence:
            # update existing page — preserve previous version in body
            existing.body = f"{new.body}\n\n---\n\n**Previous version ({existing.last_verified}):**\n\n{existing.body}"
            existing.last_verified = _now()
            existing.confidence = new.confidence
            existing.version += 1
            # Rescan paths and update
            for p in Path(self.wiki_dir).rglob("*.md"):
                page = _parse_kb_file(str(p))
                if page and page.title == existing.title:
                    _write_kb_file(str(p), existing)
                    break
        else:
            # lower-confidence conflicting info → store in conflict
            conflict_dir = os.path.join(self.pending_dir, "conflicts")
            os.makedirs(conflict_dir, exist_ok=True)
            new.title = f"[CONFLICT] {new.title}"
            _write_kb_file(os.path.join(conflict_dir, f"{new.slug}.md"), new)

    # ------------------------------------------------------------------
    # wiki promotion after pytest validation
    # ------------------------------------------------------------------

    def promote_pending(self, slug: str, verified_by: str = "pytest") -> str | None:
        """Promote pending → wiki."""
        src = os.path.join(self.pending_dir, f"{slug}.md")
        if not os.path.exists(src):
            return None
        page = _parse_kb_file(src)
        if not page:
            return None

        page.status = "active"
        page.last_verified = _now()
        page.verified_by = verified_by

        dst_dir = os.path.join(self.wiki_dir, page.domain)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{slug}.md")
        _write_kb_file(dst, page)
        os.remove(src)
        self._update_index()
        return dst

    def promote_all_pending_if_tests_pass(self, pytest_passed: bool) -> list[str]:
        """Promote all pending pages to wiki when tests pass."""
        promoted: list[str] = []
        if not pytest_passed:
            return promoted
        for p in list(Path(self.pending_dir).glob("*.md")):
            result = self.promote_pending(p.stem, verified_by="pytest")
            if result:
                promoted.append(p.stem)
        return promoted

    # ------------------------------------------------------------------
    # automatic cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> dict[str, list[str]]:
        """Automatically handle outdated or low-confidence pages.

        Returns: {"stale": [...], "deprecated": [...]}
        """
        stale: list[str] = []
        deprecated: list[str] = []

        for p in Path(self.wiki_dir).rglob("*.md"):
            if p.name == INDEX_FILE:
                continue
            page = _parse_kb_file(str(p))
            if not page:
                continue

            # below minimum confidence
            if page.confidence < MIN_CONFIDENCE:
                page.status = "deprecated"
                dst = os.path.join(self.deprecated_dir, f"{page.slug}.md")
                _write_kb_file(dst, page)
                os.remove(str(p))
                deprecated.append(page.title)
                continue

            # TTL exceeded → mark stale
            if page.is_stale and page.status != "stale":
                page.status = "stale"
                _write_kb_file(str(p), page)
                stale.append(page.title)
                continue

            # stale for too long → deprecated
            if page.status == "stale" and page.last_verified:
                try:
                    last = datetime.strptime(page.last_verified, "%Y-%m-%d")
                    if (datetime.now() - last).days > AUTO_DEPRECATE_DAYS:
                        page.status = "deprecated"
                        dst = os.path.join(self.deprecated_dir, f"{page.slug}.md")
                        _write_kb_file(dst, page)
                        os.remove(str(p))
                        deprecated.append(page.title)
                except Exception:
                    pass

        if stale:
            print(f"\033[33m  [KB] {len(stale)} stale page(s): {', '.join(stale)}\033[0m")
        if deprecated:
            print(f"\033[33m  [KB] {len(deprecated)} page(s) deprecated: {', '.join(deprecated)}\033[0m")

        self._update_index()
        return {"stale": stale, "deprecated": deprecated}

    # ------------------------------------------------------------------
    # auto-generate index.md
    # ------------------------------------------------------------------

    def _update_index(self) -> None:
        """Auto-update wiki/index.md."""
        lines = [f"# KB Index (auto-generated: {_now()})\n"]
        domains: dict[str, list[KBPage]] = {}

        for p in Path(self.wiki_dir).rglob("*.md"):
            if p.name == INDEX_FILE:
                continue
            page = _parse_kb_file(str(p))
            if page:
                domains.setdefault(page.domain, []).append(page)

        for domain, pages in sorted(domains.items()):
            lines.append(f"\n## {domain}\n")
            for page in sorted(pages, key=lambda p: p.title):
                stale = " ⚠️" if page.is_stale else ""
                rel = os.path.relpath(
                    os.path.join(self.wiki_dir, page.domain, f"{page.slug}.md"),
                    self.wiki_dir,
                )
                lines.append(f"- [{page.title}]({rel}){stale} (confidence: {page.confidence:.0%})")

        index_path = os.path.join(self.wiki_dir, INDEX_FILE)
        Path(index_path).write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # full pipeline (called after task completion)
    # ------------------------------------------------------------------

    def post_task_update(self, messages: list[dict], pytest_passed: bool) -> None:
        """Full pipeline that runs automatically after a skill completes."""
        # 1. extract domain knowledge
        facts = self.extract_from_conversation(messages, pytest_passed)
        saved = []
        for fact in facts:
            path = self.save_pending(fact)
            if path:
                saved.append(fact.get("title", ""))

        if saved:
            print(f"\033[35m  [KB] {len(saved)} new fact(s) saved to pending: {', '.join(saved)}\033[0m")

        # 2. Promote pending → wiki when tests pass
        promoted = self.promote_all_pending_if_tests_pass(pytest_passed)
        if promoted:
            print(f"\033[35m  [KB] {len(promoted)} page(s) promoted to wiki: {', '.join(promoted)}\033[0m")

        # 3. Clean up stale/deprecated
        self.cleanup()

    # ------------------------------------------------------------------
    # Status report
    # ------------------------------------------------------------------

    def status_report(self) -> str:
        wiki = list(Path(self.wiki_dir).rglob("*.md"))
        wiki = [p for p in wiki if p.name != INDEX_FILE]
        pending = list(Path(self.pending_dir).glob("*.md"))
        deprecated = list(Path(self.deprecated_dir).glob("*.md"))
        stale = [p for p in wiki if (pg := _parse_kb_file(str(p))) and pg.is_stale]

        return (
            f"[KB] wiki:{len(wiki)} (stale:{len(stale)}) "
            f"pending:{len(pending)} deprecated:{len(deprecated)}"
        )
