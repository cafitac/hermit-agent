from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_git_cwd(cwd: str, *, log_fn=None) -> str:
    """If cwd is not a git repo, search subdirectories for one and return it."""
    log = log_fn or (lambda _msg: None)

    def _is_git_repo(path: str) -> bool:
        try:
            r = subprocess.run(
                ["git", "-C", path, "rev-parse", "--git-dir"],
                capture_output=True,
                timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    if _is_git_repo(cwd):
        return cwd

    try:
        candidates = [
            str(p) for p in Path(cwd).iterdir()
            if p.is_dir() and not p.name.startswith(".") and _is_git_repo(str(p))
        ]
    except Exception:
        candidates = []

    if len(candidates) == 1:
        log(f"  i cwd '{cwd}' is not a git repo -> auto-replacing with '{candidates[0]}'")
        return candidates[0]

    if len(candidates) > 1:
        short = [Path(c).name for c in candidates[:5]]
        more = f" + {len(candidates)-5} more" if len(candidates) > 5 else ""
        log(f"  ! {len(candidates)} git repos found under cwd '{cwd}' -- {short}{more}")
    else:
        log(f"  ! no git repo found in '{cwd}' or its subdirectories")

    return cwd
