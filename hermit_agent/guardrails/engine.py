"""GuardrailEngine — guardrail activation decisions based on model profiles.

Behavior:
- registry.yaml: declares activate_when conditions for each G#
- profile YAML: capability values for the current model
- is_active(gid) → bool: result of condition evaluation
- hot-reload: detects registry/profile mtime changes → applied without session restart

fallback: if YAML is missing or corrupt → all guardrails active (regression-safe)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).parent / "registry.yaml"
_PROFILE_DEFAULTS_DIR = Path(__file__).parent.parent / "profiles" / "defaults"
_USER_PROFILES_DIR = Path.home() / ".hermit" / "profiles"

_ALWAYS_ON_FALLBACK = True  # Default value when YAML is absent


def _load_yaml(path: Path) -> dict:
    """Returns an empty dict if PyYAML is not available."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _eval_condition(value: float, expr: str) -> bool:
    """Evaluate a single condition string. Examples: '>0.2', '<=65536'."""
    expr = expr.strip()
    for op in (">=", "<=", ">", "<", "=="):
        if expr.startswith(op):
            try:
                threshold = float(expr[len(op):])
                if op == ">=":
                    return value >= threshold
                if op == "<=":
                    return value <= threshold
                if op == ">":
                    return value > threshold
                if op == "<":
                    return value < threshold
                if op == "==":
                    return value == threshold
            except ValueError:
                return True
    return True


def _eval_activate_when(activate_when: Any, capabilities: dict) -> bool:
    """Evaluate the activate_when condition tree. Unmet condition → guardrail inactive."""
    if activate_when is None:
        return True

    if isinstance(activate_when, dict):
        if "all" in activate_when:
            return all(_eval_activate_when(c, capabilities) for c in activate_when["all"])
        if "any" in activate_when:
            return any(_eval_activate_when(c, capabilities) for c in activate_when["any"])
        # single {dim: expr}
        for dim, expr in activate_when.items():
            cap_value = capabilities.get(dim)
            if cap_value is None:
                return True  # unknown capability → activate safely
            return _eval_condition(float(cap_value), str(expr))

    return True


class GuardrailEngine:
    """Guardrail activation decision engine (supports hot-reload)."""

    def __init__(self, model_id: str | None = None, registry_path: Path | None = None):
        self._model_id = model_id
        self._registry_path = registry_path or _REGISTRY_PATH
        self._lock = threading.Lock()
        self._registry: dict = {}
        self._profile: dict = {}
        self._registry_mtime: float = 0.0
        self._profile_path: Path | None = None
        self._profile_mtime: float = 0.0
        self._load_all()

    def _resolve_profile_path(self) -> Path | None:
        """Return the profile file path matching the model ID. Falls back to unknown.yaml."""
        if self._model_id:
            slug = self._model_id.replace(":", "-").replace("/", "-")
            for base in (_USER_PROFILES_DIR, _PROFILE_DEFAULTS_DIR):
                candidate = base / f"{slug}.yaml"
                if candidate.exists():
                    return candidate

        unknown = _PROFILE_DEFAULTS_DIR / "unknown.yaml"
        return unknown if unknown.exists() else None

    def _load_all(self) -> None:
        try:
            self._registry = _load_yaml(self._registry_path)
            self._registry_mtime = self._registry_path.stat().st_mtime if self._registry_path.exists() else 0.0
        except Exception:
            self._registry = {}
            self._registry_mtime = 0.0

        self._profile_path = self._resolve_profile_path()
        try:
            if self._profile_path and self._profile_path.exists():
                self._profile = _load_yaml(self._profile_path)
                self._profile_mtime = self._profile_path.stat().st_mtime
            else:
                self._profile = {}
                self._profile_mtime = 0.0
        except Exception:
            self._profile = {}
            self._profile_mtime = 0.0

    def _reload_if_changed(self) -> None:
        """Reload when mtime has changed. On failure, keeps the existing in-memory data."""
        try:
            rm = self._registry_path.stat().st_mtime if self._registry_path.exists() else 0.0
            pm = self._profile_path.stat().st_mtime if (self._profile_path and self._profile_path.exists()) else 0.0
        except Exception:
            return

        if rm == self._registry_mtime and pm == self._profile_mtime:
            return

        try:
            new_registry = _load_yaml(self._registry_path) if rm != self._registry_mtime else self._registry
            new_profile = _load_yaml(self._profile_path) if (pm != self._profile_mtime and self._profile_path) else self._profile
            self._registry = new_registry
            self._profile = new_profile
            self._registry_mtime = rm
            self._profile_mtime = pm
        except Exception:
            pass  # keep previous values if corrupt

    def is_active(self, gid: str) -> bool:
        """Return whether the given G# is currently active."""
        with self._lock:
            self._reload_if_changed()

            entry = self._registry.get(gid)
            if entry is None:
                return _ALWAYS_ON_FALLBACK

            if entry.get("always_active", False):
                return True

            capabilities = self._profile.get("capabilities", {})
            if not capabilities:
                return _ALWAYS_ON_FALLBACK  # no profile → activate all

            activate_when = entry.get("activate_when")
            return _eval_activate_when(activate_when, capabilities)

    def active_guardrails(self) -> list[str]:
        """Return the list of currently active G# identifiers."""
        with self._lock:
            self._reload_if_changed()
            return [gid for gid in self._registry if self.is_active(gid)]


# global singleton (lazy init)
_engine: GuardrailEngine | None = None
_engine_lock = threading.Lock()


def get_engine(model_id: str | None = None) -> GuardrailEngine:
    """Return the global engine. Re-initializes on first call or when model_id changes."""
    global _engine
    with _engine_lock:
        if _engine is None or (model_id is not None and _engine._model_id != model_id):
            _engine = GuardrailEngine(model_id=model_id)
        return _engine


def is_active(gid: str, model_id: str | None = None) -> bool:
    """Module-level convenience function."""
    return get_engine(model_id).is_active(gid)


__all__ = ["GuardrailEngine", "get_engine", "is_active"]
