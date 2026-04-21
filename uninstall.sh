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
# Bridge and any other `python -m hermit_agent.*` children (spawned by
# Claude Code MCP clients, launch agents, etc). We kill them by PID
# rather than invoking a stop script because there is no dedicated one.
OTHER_PIDS="$(pgrep -f 'hermit_agent\.(bridge|[a-z_]+)' 2>/dev/null \
  | xargs -I{} sh -c 'ps -p {} -o pid,command= 2>/dev/null' \
  | grep -v 'hermit_agent\.\(gateway\|mcp_server\)' \
  | awk '{print $1}' || true)"
if [ -n "$OTHER_PIDS" ]; then
  say "Found other hermit_agent processes still running:"
  for _pid in $OTHER_PIDS; do
    ps -p "$_pid" -o pid,command= 2>/dev/null | sed 's/^/   /'
  done
  if confirm "Stop them?"; then
    for _pid in $OTHER_PIDS; do
      kill "$_pid" 2>/dev/null && say "  killed $_pid" || warn "  could not kill $_pid"
    done
  fi
fi

# ──────────────────────────────────────────────────────────────
# 0.5 Project-local Codex channels wiring (workspace marketplace,
#     local state, and `.hermit/settings.json` codex_channels block).
# ──────────────────────────────────────────────────────────────
PROJECT_SETTINGS="$PROJECT_DIR/.hermit/settings.json"
PROJECT_MARKETPLACE="$PROJECT_DIR/.agents/plugins/marketplace.json"
PROJECT_CODEX_STATE="$PROJECT_DIR/.codex-channels"
if [ -f "$PROJECT_SETTINGS" ] || [ -f "$PROJECT_MARKETPLACE" ] || [ -d "$PROJECT_CODEX_STATE" ]; then
  if confirm "Remove project-local Codex channels setup (.hermit/settings.json block, marketplace entry, local state)?"; then
    PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$PROJECT_DIR" <<'PYEOF'
import sys
from hermit_agent.codex_channels_adapter import (
    remove_codex_channels_settings,
    remove_marketplace_plugin_entry,
    remove_plugin_dir,
    remove_runtime_dir,
)

cwd = sys.argv[1]
remove_codex_channels_settings(cwd)
remove_marketplace_plugin_entry(cwd)
remove_plugin_dir(cwd)
remove_runtime_dir(cwd)
PYEOF
    if [ -d "$PROJECT_CODEX_STATE" ]; then
      rm -rf "$PROJECT_CODEX_STATE"
      say "Removed $PROJECT_CODEX_STATE"
    fi
    say "Removed project-local Codex channels setup"
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
      # Regular file (not a symlink install.sh would have made).
      # Offer to delete but warn explicitly — may be user-edited.
      if confirm "Remove regular file $link (not a symlink — may contain your edits)?"; then
        rm -f "$link"
        say "Removed $link"
        REMOVED_ANY=1
      else
        say "Leaving $link"
      fi
    fi
  done
  [ "$REMOVED_ANY" -eq 0 ] && say "No hermit-command files to remove."
fi

# ──────────────────────────────────────────────────────────────
# 4. ~/.claude.json — remove every Hermit MCP entry (current + legacy)
# ──────────────────────────────────────────────────────────────
if [ -f "$CLAUDE_JSON" ]; then
  if confirm "Remove Hermit MCP entries (hermit-channel + legacy hermit) from $CLAUDE_JSON?"; then
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

# Names to scrub:
#   - "hermit-channel": current single-source-of-truth registration
#   - "hermit": legacy HTTP entry left over from older installs that
#     used a separate :3737 daemon (now consolidated into hermit-channel)
NAMES = ("hermit-channel", "hermit")
removed = []

# Top-level mcpServers (user-wide).
servers = data.get("mcpServers")
if isinstance(servers, dict):
    for name in NAMES:
        if name in servers:
            del servers[name]
            removed.append(f"mcpServers.{name}")
    if not servers:
        del data["mcpServers"]

# Per-project mcpServers blocks.
projects = data.get("projects")
if isinstance(projects, dict):
    for proj_name, proj in list(projects.items()):
        if not isinstance(proj, dict):
            continue
        pservers = proj.get("mcpServers")
        if not isinstance(pservers, dict):
            continue
        for name in NAMES:
            if name in pservers:
                del pservers[name]
                removed.append(f"projects[{proj_name}].mcpServers.{name}")
        if not pservers:
            del proj["mcpServers"]

if not removed:
    print("UNCHANGED (no hermit MCP entry found)")
    sys.exit(0)

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("REMOVED: " + ", ".join(removed))
PYEOF
    rc=$?
    if [ "$rc" = "0" ]; then
      say "Hermit MCP entries removed from $CLAUDE_JSON (backup written)"
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

# ──────────────────────────────────────────────────────────────
# 6. Shell rc — remove HERMIT_* env exports (HERMIT_AUTO_WRAP,
#    HERMIT_API_KEY, etc). User may have set these manually; we
#    prompt per line.
# ──────────────────────────────────────────────────────────────
for RC_FILE in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
  [ -f "$RC_FILE" ] || continue
  # Lines like: export HERMIT_xxx=... / HERMIT_xxx=...
  MATCHES="$(grep -nE '^[[:space:]]*(export[[:space:]]+)?HERMIT_[A-Z_]+=' "$RC_FILE" || true)"
  [ -z "$MATCHES" ] && continue
  echo "Found HERMIT_* env lines in $RC_FILE:"
  printf '%s\n' "$MATCHES" | sed 's/^/   /'
  if confirm "Remove these lines from $RC_FILE?"; then
    cp "$RC_FILE" "$RC_FILE.backup-$(date +%Y%m%d-%H%M%S)"
    # Extract line numbers to delete, in descending order so indices
    # stay valid as we pop them.
    LINES_DESC="$(printf '%s\n' "$MATCHES" | cut -d: -f1 | sort -rn)"
    python3 - "$RC_FILE" "$LINES_DESC" <<'PYEOF'
import sys
path = sys.argv[1]
lines_desc = [int(x) for x in sys.argv[2].split()]
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()
# Also drop a blank "# Hermit …" comment immediately above if present.
for ln in lines_desc:
    idx = ln - 1
    if idx < 0 or idx >= len(lines):
        continue
    del lines[idx]
    # Remove an orphaned header comment directly above.
    if idx - 1 >= 0 and lines[idx - 1].strip().lower().startswith("# hermit"):
        # Only remove if the NEXT line (post-delete) is blank or another
        # section heading — avoids eating unrelated comments.
        if idx >= len(lines) or not lines[idx].strip().lower().startswith("export hermit") \
           and not lines[idx].strip().lower().startswith("hermit_"):
            del lines[idx - 1]
with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
PYEOF
    say "Removed HERMIT_* lines from $RC_FILE (backup written)"
  fi
done

say "Uninstall complete."
echo "  - Ollama models are untouched. Run \`ollama rm qwen3-coder:30b\` (or similar) to reclaim disk."
echo "  - The repo itself is untouched. Delete the project directory manually if you no longer need it."
echo "  - Your current shell has a cached \`hermit\` alias and any \`HERMIT_*\` env vars."
echo "    Run \`unalias hermit\` + \`unset \$(env | grep ^HERMIT_ | cut -d= -f1)\`,"
echo "    or just open a new terminal, so they stop leaking into new commands."
