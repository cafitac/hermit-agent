"""Session store for HermitAgent — manages session metadata, messages, and events."""

import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def cwd_slug(path: str) -> str:
    """Replace every non-alphanumeric character with a dash.

    Hermit uses MD5 hex while Claude Code uses djb2 base-36 — divergence intentional.
    """
    result = re.sub(r'[^a-zA-Z0-9]', '-', path)
    if len(result) <= 200:
        return result
    return result[:200] + '-' + hashlib.md5(path.encode()).hexdigest()[:8]


def read_jsonl(path: str) -> list[dict]:
    """Read a JSONL file, skipping blank and corrupt lines."""
    if not os.path.exists(path):
        return []
    records: list[dict] = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON to *path* atomically via tmp+rename."""
    import uuid as _uuid
    tmp = f"{path}.{_uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def derive_preview(messages: list[dict], max_chars: int = 80) -> str:
    """Extract a short preview from the first user message."""
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            content = msg["content"]
            content = re.sub(
                r"^(?:<(?:context|session-handoff|learned_feedback)>\n.*?\n</(?:context|session-handoff|learned_feedback)>\n\n)+",
                "",
                content,
                flags=re.DOTALL,
            )
            return content[:max_chars]
    return ""


def _parse_updated_at(meta: dict) -> float:
    """Convert updated_at to epoch seconds for sorting."""
    val = meta.get('updated_at')
    if isinstance(val, (int, float)):
        return float(val)
    # ISO8601 string
    if not isinstance(val, str):
        return 0.0
    try:
        return datetime.strptime(val, '%Y-%m-%dT%H:%M:%SZ').timestamp()
    except ValueError:
        return 0.0


class SessionStore:
    """Manage Hermit session directories, metadata, and legacy fallback."""

    def __init__(
        self,
        root: Optional[str] = None,
        legacy_root: Optional[str] = None,
    ) -> None:
        self.root = root or os.path.expanduser('~/.hermit/logs')
        self.legacy_root = legacy_root or os.path.expanduser('~/.hermit/sessions')

    def create_session(
        self,
        mode: str,
        session_id: str,
        cwd: str,
        model: Optional[str] = None,
        parent_session_id: Optional[str] = None,
    ) -> str:
        """Create a new session directory with meta.json. Returns the session dir path."""
        slug = cwd_slug(cwd)
        session_dir = os.path.join(self.root, mode, slug, session_id)
        os.makedirs(session_dir, exist_ok=True)

        now = _utc_now_iso()
        meta = {
            'session_id': session_id,
            'mode': mode,
            'cwd': cwd,
            'model': model,
            'status': 'active',
            'parent_session_id': parent_session_id,
            'created_at': now,
            'updated_at': now,
            'turn_count': 0,
            'preview': '',
        }
        _atomic_write_json(os.path.join(session_dir, 'meta.json'), meta)
        return os.path.abspath(session_dir)

    def update_meta(self, session_dir: str, **fields: Any) -> None:
        """Update fields in an existing meta.json and rewrite atomically."""
        meta = self.get_meta(session_dir)
        meta.update(fields)
        meta['updated_at'] = _utc_now_iso()
        _atomic_write_json(os.path.join(session_dir, 'meta.json'), meta)

    def write_messages(self, session_dir: str, messages: list[dict]) -> str:
        """Persist canonical transcript payload to messages.json."""
        path = os.path.join(session_dir, "messages.json")
        _atomic_write_json(path, messages)
        return path

    def update_transcript_state(
        self,
        session_dir: str,
        *,
        messages: list[dict],
        turn_count: int,
        status: str | None = None,
    ) -> None:
        """Persist transcript and keep meta preview/turn-count in sync."""
        self.write_messages(session_dir, messages)
        meta_fields: dict[str, Any] = {
            "turn_count": turn_count,
            "preview": derive_preview(messages),
        }
        if status is not None:
            meta_fields["status"] = status
        self.update_meta(session_dir, **meta_fields)

    def get_meta(self, session_dir: str) -> dict:
        """Read and return the meta.json for a session."""
        meta_path = os.path.join(session_dir, 'meta.json')
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f'meta.json not found in {session_dir}')
        with open(meta_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def find_session_dir(
        self,
        session_id: str,
        mode: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """Return the new-layout session directory when present."""
        return self._find_new_session(session_id, mode, cwd)

    def load_session(
        self,
        session_id: str,
        mode: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Optional[dict]:
        """Load a session by id, with optional mode/cwd hints. Falls back to legacy."""
        # Try new layout
        session_dir = self._find_new_session(session_id, mode, cwd)
        if session_dir is not None:
            meta = self.get_meta(session_dir)
            messages_path = os.path.join(session_dir, 'messages.json')
            messages = None
            if os.path.exists(messages_path):
                with open(messages_path, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
            events_path = os.path.join(session_dir, 'events.jsonl')
            events = read_jsonl(events_path) if os.path.exists(events_path) else None
            return {'meta': meta, 'messages': messages, 'events': events}

        # Legacy fallback
        legacy_path = os.path.join(self.legacy_root, f'{session_id}.json')
        if os.path.exists(legacy_path):
            with open(legacy_path, 'r', encoding='utf-8') as f:
                legacy = json.load(f)
            return {
                'meta': legacy['meta'],
                'messages': legacy.get('messages'),
                'events': None,
            }
        return None

    def list_sessions(
        self,
        mode: Optional[str] = None,
        cwd: Optional[str] = None,
        limit: int = 20,
        parent_session_id: Optional[str] = None,
    ) -> list[dict]:
        """List sessions sorted by updated_at desc, capped at limit."""
        results: list[dict] = []

        # New layout
        root_path = Path(self.root)
        if root_path.exists():
            mode_dirs = sorted(root_path.iterdir()) if mode is None else [root_path / mode]
            for md in mode_dirs:
                if not md.is_dir():
                    continue
                for cwd_dir in sorted(md.iterdir()):
                    if not cwd_dir.is_dir():
                        continue
                    for sid_dir in sorted(cwd_dir.iterdir()):
                        if not sid_dir.is_dir():
                            continue
                        meta_path = sid_dir / 'meta.json'
                        if not meta_path.exists():
                            continue
                        with open(meta_path, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                        if cwd is not None and meta.get('cwd') != cwd:
                            continue
                        if parent_session_id is not None and meta.get('parent_session_id') != parent_session_id:
                            continue
                        results.append(meta)

        # Legacy layout — only when mode is None or 'single'
        if mode is None or mode == 'single':
            legacy_path = Path(self.legacy_root)
            if legacy_path.exists():
                for fp in sorted(legacy_path.glob('*.json')):
                    with open(fp, 'r', encoding='utf-8') as f:
                        legacy = json.load(f)
                    meta = legacy.get('meta', {})
                    # Ensure session_id is present
                    if 'session_id' not in meta:
                        meta['session_id'] = fp.stem
                    if mode is not None and meta.get('mode') != mode:
                        # Legacy sessions don't always have mode; include them
                        # when mode filter is 'single' as a default
                        pass
                    if cwd is not None and meta.get('cwd') != cwd:
                        continue
                    if parent_session_id is not None and meta.get('parent_session_id') != parent_session_id:
                        continue
                    results.append(meta)

        results.sort(key=_parse_updated_at, reverse=True)
        return results[:limit]

    def _find_new_session(
        self,
        session_id: str,
        mode: Optional[str],
        cwd: Optional[str],
    ) -> Optional[str]:
        """Find session directory in the new layout."""
        if mode is not None and cwd is not None:
            d = os.path.join(self.root, mode, cwd_slug(cwd), session_id)
            if os.path.isdir(d):
                return d
            return None

        # Walk all mode/cwd directories
        root_path = Path(self.root)
        if not root_path.exists():
            return None
        for md in root_path.iterdir():
            if not md.is_dir():
                continue
            for cwd_dir in md.iterdir():
                if not cwd_dir.is_dir():
                    continue
                candidate = cwd_dir / session_id
                if candidate.is_dir():
                    return str(candidate)
        return None
