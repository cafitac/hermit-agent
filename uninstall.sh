#!/usr/bin/env bash
# HermitAgent uninstaller — reverses install.sh side effects.
#
# Each step prompts individually so you can pick & choose (e.g. keep
# your ~/.hermit/settings.json and handoffs while removing the MCP
# registration and shell alias). Idempotent — safe to re-run.
#
# Usage:
#   ./uninstall.sh              # interactive
#   ./uninstall.sh --yes        # accept every step without prompting
#   ./uninstall.sh --keep-data  # never touch ~/.hermit/ (settings, db, handoffs)
#
# Notes:
#   * Ollama models are NOT deleted (they're easy to keep and a re-pull
#     is expensive). Remove manually with `ollama rm qwen3-coder:30b`.
#   * Any file that uninstall.sh rewrites is backed up first with a
#     timestamped `.backup-<ts>` suffix.

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
HERMIT_HOME="$HOME/.hermit"
HERMIT_BIN_OLD="$PROJECT_DIR/hermit.sh"
HERMIT_BIN_NEW="$PROJECT_DIR/bin/hermit.sh"
CLAUDE_JSON="$HOME/.claude.json"
CC_CMDS_DIR="$HOME/.claude/commands"

ASSUME_YES=0
KEEP_DATA=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --keep-data) KEEP_DATA=1 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
  esac
done

say()  { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*" >&2; }

confirm() {
  # confirm "Question?" -> returns 0 (yes) or 1 (no). Default yes.
  if [ "$ASSUME_YES" -eq 1 ]; then return 0; fi
  printf "%s [Y/n] " "$1"
  read -r reply || reply="y"
  case "$(echo "${reply:-y}" | tr '[:upper:]' '[:lower:]')" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

# ──────────────────────────────────────────────────────────────
# 0. Stop running daemons first (before we touch the venv —
#    the start scripts cache import paths that break once .venv
#    is gone, so stopping here keeps the rest of the run clean).
# ──────────────────────────────────────────────────────────────
if pgrep -f 'hermit_agent\.gateway' >/dev/null 2>&1; then
  if confirm "Stop running gateway daemon?"; then
    "$PROJECT_DIR/bin/gateway.sh" --stop || true
  fi
fi
if pgrep -f 'hermit_agent\.mcp_server' >/dev/null 2>&1; then
  if confirm "Stop running MCP server?"; then
    "$PROJECT_DIR/bin/mcp-server.sh" --stop || true
  fi
fi

# ──────────────────────────────────────────────────────────────
# 1. ~/.hermit/ — settings, gateway.db, handoffs, logs
# ──────────────────────────────────────────────────────────────
if [ -d "$HERMIT_HOME" ]; then
  if [ "$KEEP_DATA" -eq 1 ]; then
    say "Keeping $HERMIT_HOME (--keep-data)."
  elif confirm "Remove $HERMIT_HOME (settings, gateway.db, handoffs, logs)?"; then
    rm -rf "$HERMIT_HOME"
    say "Removed $HERMIT_HOME"
  else
    say "Keeping $HERMIT_HOME"
  fi
else
  say "$HERMIT_HOME does not exist — skipping."
fi

# ──────────────────────────────────────────────────────────────
# 2. Project venv
# ──────────────────────────────────────────────────────────────
if [ -d "$VENV_DIR" ]; then
  if confirm "Remove project venv at $VENV_DIR?"; then
    rm -rf "$VENV_DIR"
    say "Removed $VENV_DIR"
  else
    say "Keeping $VENV_DIR"
  fi
else
  say "No venv at $VENV_DIR — skipping."
fi

# ──────────────────────────────────────────────────────────────
# 3. ~/.claude/commands/*-hermit.md symlinks (remove only those
#    pointing at this repo — leave hand-edited regular files alone)
# ──────────────────────────────────────────────────────────────
if [ -d "$CC_CMDS_DIR" ]; then
  REMOVED_ANY=0
  for link in "$CC_CMDS_DIR"/*-hermit.md; do
    [ -e "$link" ] || continue
    if [ -L "$link" ]; then
      target="$(readlink "$link")"
      case "$target" in
        "$PROJECT_DIR"/*|"$PROJECT_DIR")
          if confirm "Remove symlink $link → $target?"; then
            rm -f "$link"
            say "Removed $link"
            REMOVED_ANY=1
          fi
          ;;
        *)
          say "Leaving $link (points outside this repo: $target)"
          ;;
      esac
    else
      say "Leaving $link (regular file, not a symlink we created)"
    fi
  done
  [ "$REMOVED_ANY" -eq 0 ] && say "No hermit-command symlinks to remove."
fi

# ──────────────────────────────────────────────────────────────
# 4. ~/.claude.json — remove hermit-channel MCP entry
# ──────────────────────────────────────────────────────────────
if [ -f "$CLAUDE_JSON" ]; then
  if confirm "Remove hermit-channel MCP entry from $CLAUDE_JSON?"; then
    python3 - "$CLAUDE_JSON" <<'PYEOF'
import json, os, shutil, sys
from datetime import datetime

path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception as e:
    print(f"FAIL: cannot parse {path}: {e}", file=sys.stderr)
    sys.exit(2)

ts = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copyfile(path, f"{path}.backup-{ts}")

name = "hermit-channel"
removed = False

# Top-level mcpServers (user-wide).
servers = data.get("mcpServers")
if isinstance(servers, dict) and name in servers:
    del servers[name]
    removed = True
    if not servers:
        del data["mcpServers"]

# Per-project mcpServers blocks.
projects = data.get("projects")
if isinstance(projects, dict):
    for proj_name, proj in list(projects.items()):
        if not isinstance(proj, dict):
            continue
        pservers = proj.get("mcpServers")
        if isinstance(pservers, dict) and name in pservers:
            del pservers[name]
            removed = True
            if not pservers:
                del proj["mcpServers"]

if not removed:
    print("UNCHANGED (no hermit-channel entry found)")
    sys.exit(0)

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("REMOVED")
PYEOF
    rc=$?
    if [ "$rc" = "0" ]; then
      say "hermit-channel removed from $CLAUDE_JSON (backup written)"
    elif [ "$rc" = "2" ]; then
      warn "Could not parse $CLAUDE_JSON — leaving it alone."
    fi
  fi
else
  say "$CLAUDE_JSON does not exist — skipping."
fi

# ──────────────────────────────────────────────────────────────
# 5. Shell rc — remove the `hermit` alias line we added
# ──────────────────────────────────────────────────────────────
for RC_FILE in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
  [ -f "$RC_FILE" ] || continue
  LINE_NO="$(grep -n '^[[:space:]]*alias[[:space:]]\+hermit=' "$RC_FILE" | head -1 | cut -d: -f1 || true)"
  [ -z "$LINE_NO" ] && continue
  EXISTING_LINE="$(sed -n "${LINE_NO}p" "$RC_FILE")"
  case "$EXISTING_LINE" in
    *"$HERMIT_BIN_NEW"*|*"$HERMIT_BIN_OLD"*)
      if confirm "Remove hermit alias from $RC_FILE ($EXISTING_LINE)?"; then
        cp "$RC_FILE" "$RC_FILE.backup-$(date +%Y%m%d-%H%M%S)"
        python3 - "$RC_FILE" "$LINE_NO" <<'PYEOF'
import sys
path, line_no = sys.argv[1], int(sys.argv[2])
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()
# Drop the alias line, plus an adjacent `# Added by hermit-agent install.sh`
# marker comment above it (if present).
keep = []
skip_next_marker = False
for idx, line in enumerate(lines, start=1):
    if idx == line_no:
        continue
    if idx == line_no - 1 and line.strip().startswith("# Added by hermit-agent install.sh"):
        continue
    keep.append(line)
with open(path, "w", encoding="utf-8") as f:
    f.writelines(keep)
PYEOF
        say "Removed hermit alias from $RC_FILE (backup written)"
      fi
      ;;
    *)
      say "Leaving alias in $RC_FILE (points elsewhere: $EXISTING_LINE)"
      ;;
  esac
done

say "Uninstall complete."
echo "  - Ollama models are untouched. Run \`ollama rm qwen3-coder:30b\` (or similar) to reclaim disk."
echo "  - The repo itself is untouched. Delete the project directory manually if you no longer need it."
echo "  - Your current shell has a cached \`hermit\` alias. Run \`unalias hermit\`"
echo "    (or \`source ~/.zshrc\` / open a new shell) so it stops pointing at the old path."
