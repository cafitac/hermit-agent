#!/usr/bin/env bash
# HermitAgent one-shot installer.
#
# Creates a project-local venv, bootstraps uv inside it, installs the
# Python package via uv, writes a default ~/.hermit/settings.json if
# missing, optionally mints a gateway API key in ~/.hermit/gateway.db,
# and (optionally) pulls a local ollama coding model.
# Idempotent — safe to re-run.
#
# Usage:
#   ./install.sh                    # interactive
#   ./install.sh --no-ollama        # skip the ollama prompt
#   ./install.sh --skip-venv        # reuse an existing .venv
#   ./install.sh --no-api-key       # skip the gateway API key prompt
#   ./install.sh --no-mcp-register  # skip the ~/.claude.json MCP registration prompt
#   ./install.sh --no-alias         # skip the shell-rc alias prompt
#   ./install.sh --generate-friend-key  # mint a scoped friend key (local platform only)
#   ./install.sh --dry-run          # only run the settings sanity check, then exit

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
SETTINGS_DIR="$HOME/.hermit"
SETTINGS_FILE="$SETTINGS_DIR/settings.json"

SKIP_OLLAMA=0
SKIP_VENV=0
SKIP_API_KEY=0
SKIP_MCP_REGISTER=0
SKIP_ALIAS=0
MCP_REGISTERED_BY_INSTALLER=0
GENERATE_FRIEND_KEY=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --no-ollama) SKIP_OLLAMA=1 ;;
    --skip-venv) SKIP_VENV=1 ;;
    --no-api-key) SKIP_API_KEY=1 ;;
    --no-mcp-register) SKIP_MCP_REGISTER=1 ;;
    --no-alias) SKIP_ALIAS=1 ;;
    --generate-friend-key) GENERATE_FRIEND_KEY=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,19p' "$0"
      exit 0
      ;;
  esac
done

PENDING_STEPS=()

say()  { printf "\033[1;36m▸\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*" >&2; }

# 0. Settings rename sanity check (US-008).
#    Warn when an existing settings.json carries a non-empty llm_api_key but
#    the platform ACL tables (migration 002) are not yet present — this is the
#    shape from before the two-endpoint model was introduced.
GATEWAY_DB_CHECK="$HOME/.hermit/gateway.db"
SETTINGS_FILE_CHECK="$HOME/.hermit/settings.json"
if [ -f "$SETTINGS_FILE_CHECK" ]; then
  _existing_llm_key="$(python3 -c "
import json, sys
try:
    d = json.load(open('$SETTINGS_FILE_CHECK'))
    print(d.get('llm_api_key', ''))
except Exception:
    print('')
" 2>/dev/null || true)"
  if [ -n "$_existing_llm_key" ]; then
    # Check whether migration 002 has been applied (api_key_platform table exists).
    _acl_present=0
    if [ -f "$GATEWAY_DB_CHECK" ] && command -v sqlite3 >/dev/null; then
      _tbl="$(sqlite3 "$GATEWAY_DB_CHECK" "SELECT name FROM sqlite_master WHERE type='table' AND name='api_key_platform';" 2>/dev/null || true)"
      [ -n "$_tbl" ] && _acl_present=1
    fi
    if [ "$_acl_present" -eq 0 ]; then
      warn "Please review: your llm_api_key now represents the gateway's upstream provider credential (z.ai, etc.), not your client-facing gateway key. If you previously used llm_api_key for a different purpose, edit ~/.hermit/settings.json. See docs/cc-setup.md § new-two-endpoint-model."
    fi
  fi
fi

# --dry-run: only run the sanity check above, then exit.
if [ "$DRY_RUN" -eq 1 ]; then
  exit 0
fi

# 1. Python version check
if ! command -v python3 >/dev/null; then
  warn "python3 not found on PATH. Install Python 3.11+ first."
  exit 1
fi
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  warn "Python 3.11+ required (found $PY_MAJOR.$PY_MINOR)."
  exit 1
fi

# 2. venv
if [ "$SKIP_VENV" -eq 0 ]; then
  if [ -d "$VENV_DIR" ]; then
    say "Reusing existing venv at $VENV_DIR"
  else
    say "Creating venv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
VENV_UV="$VENV_DIR/bin/uv"

# 3. bootstrap uv inside the venv — single pip invocation, everything
#    else runs through uv (much faster resolver + installer).
if [ ! -x "$VENV_UV" ]; then
  say "Bootstrapping uv inside the venv"
  "$VENV_PIP" install --quiet --upgrade pip
  "$VENV_PIP" install --quiet uv
fi

# 4. deps — all via uv
say "Installing project (uv pip install -e .)"
"$VENV_UV" pip install --python "$VENV_PY" -e ".[test]" --quiet

# 5. settings.json scaffold
mkdir -p "$SETTINGS_DIR"
if [ -f "$SETTINGS_FILE" ]; then
  say "Found existing settings at $SETTINGS_FILE — leaving it alone"
else
  say "Writing default settings to $SETTINGS_FILE"
  cat > "$SETTINGS_FILE" <<'EOF'
{
  "gateway_url": "http://localhost:8765",
  "gateway_api_key": "CHANGE_ME_AFTER_FIRST_RUN",
  "model": "glm-5.1",
  "response_language": "auto",
  "compact_instructions": ""
}
EOF
fi

# 5.5 optional: generate a random gateway API key, persist to gateway.db,
#     and patch settings.json. The gateway DB schema lives in migrations/;
#     we apply it with sqlite3 so the installer does not have to start the
#     gateway first.
if [ "$SKIP_API_KEY" -eq 0 ]; then
  current_key=$(python3 -c "import json; print(json.load(open('$SETTINGS_FILE')).get('gateway_api_key',''))" 2>/dev/null || echo "")
  if [ "$current_key" != "" ] && [ "$current_key" != "CHANGE_ME_AFTER_FIRST_RUN" ]; then
    say "Gateway API key already set in settings.json — skipping generation."
  elif ! command -v sqlite3 >/dev/null; then
    warn "sqlite3 not on PATH — skipping API key generation."
    PENDING_STEPS+=("Install sqlite3 and generate a gateway API key (see docs/cc-setup.md step 2).")
  else
    printf "\033[1;36m▸\033[0m Generate a random gateway API key now? [Y/n] "
    read -r reply || reply="n"
    if [[ -z "$reply" || "$reply" =~ ^[Yy]$ ]]; then
      GATEWAY_DB="$SETTINGS_DIR/gateway.db"
      MIGRATION_FILE="$PROJECT_DIR/hermit_agent/gateway/migrations/001_initial.sql"
      if [ ! -f "$MIGRATION_FILE" ]; then
        warn "Migration file not found at $MIGRATION_FILE — skipping."
        PENDING_STEPS+=("Generate a gateway API key manually (see docs/cc-setup.md step 2).")
      else
        sqlite3 "$GATEWAY_DB" < "$MIGRATION_FILE" >/dev/null 2>&1 || true
        # Apply migration 002 (platform ACL tables) — idempotent via IF NOT EXISTS.
        MIGRATION_002="$PROJECT_DIR/hermit_agent/gateway/migrations/002_platform_acl.sql"
        if [ -f "$MIGRATION_002" ]; then
          _acl_already=0
          _tbl2="$(sqlite3 "$GATEWAY_DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='api_key_platform';" 2>/dev/null || true)"
          [ -n "$_tbl2" ] && _acl_already=1
          if [ "$_acl_already" -eq 1 ]; then
            say "Platform ACL tables already present — skipping migration 002."
          else
            sqlite3 "$GATEWAY_DB" < "$MIGRATION_002" >/dev/null 2>&1 || true
            say "Applied migration 002 (platform ACL)."
          fi
        fi
        NEW_KEY="hermit-mcp-$(openssl rand -base64 24 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c 32)"
        if [ -z "$NEW_KEY" ] || [ "$NEW_KEY" = "hermit-mcp-" ]; then
          NEW_KEY="hermit-mcp-$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(32)))')"
        fi
        if sqlite3 "$GATEWAY_DB" "INSERT INTO api_keys(api_key, user) VALUES ('$NEW_KEY', 'local');" >/dev/null 2>&1; then
          # Backfill platform access for the new operator key (all 4 platforms = full access).
          sqlite3 "$GATEWAY_DB" "INSERT INTO api_key_platform SELECT '$NEW_KEY', slug FROM platforms ON CONFLICT DO NOTHING;" >/dev/null 2>&1 || true
          python3 - "$SETTINGS_FILE" "$NEW_KEY" <<'PYEOF'
import json, sys
path, key = sys.argv[1], sys.argv[2]
data = json.load(open(path))
data["gateway_api_key"] = key
open(path, "w").write(json.dumps(data, indent=2) + "\n")
PYEOF
          say "Generated API key and updated $SETTINGS_FILE."
        else
          warn "sqlite INSERT failed — leaving gateway_api_key unchanged."
          PENDING_STEPS+=("Generate a gateway API key manually (see docs/cc-setup.md step 2).")
        fi
      fi
    else
      say "Skipped API key generation — using placeholder value."
      PENDING_STEPS+=("Generate a gateway API key (docs/cc-setup.md step 2) and replace \"CHANGE_ME_AFTER_FIRST_RUN\" in $SETTINGS_FILE.")
    fi
  fi
fi

# 5.6 optional: generate a scoped "friend key" (local platform only).
#     Activated by --generate-friend-key flag. The key is NOT written to
#     settings.json — it is printed for the operator to hand out.
if [ "$GENERATE_FRIEND_KEY" -eq 1 ]; then
  GATEWAY_DB="$SETTINGS_DIR/gateway.db"
  MIGRATION_FILE="$PROJECT_DIR/hermit_agent/gateway/migrations/001_initial.sql"
  MIGRATION_002="$PROJECT_DIR/hermit_agent/gateway/migrations/002_platform_acl.sql"
  if ! command -v sqlite3 >/dev/null; then
    warn "sqlite3 not on PATH — cannot generate friend key."
  elif [ ! -f "$MIGRATION_FILE" ]; then
    warn "Migration 001 not found — cannot generate friend key."
  else
    sqlite3 "$GATEWAY_DB" < "$MIGRATION_FILE" >/dev/null 2>&1 || true
    [ -f "$MIGRATION_002" ] && sqlite3 "$GATEWAY_DB" < "$MIGRATION_002" >/dev/null 2>&1 || true
    _ts="$(date +%s)"
    FRIEND_KEY="hermit-friend-$(openssl rand -base64 24 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c 32)"
    if [ -z "$FRIEND_KEY" ] || [ "$FRIEND_KEY" = "hermit-friend-" ]; then
      FRIEND_KEY="hermit-friend-$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(32)))')"
    fi
    if sqlite3 "$GATEWAY_DB" "INSERT INTO api_keys(api_key, user) VALUES ('$FRIEND_KEY', 'friend-$_ts');" >/dev/null 2>&1; then
      sqlite3 "$GATEWAY_DB" "INSERT INTO api_key_platform(api_key, platform_slug) VALUES ('$FRIEND_KEY', 'local') ON CONFLICT DO NOTHING;" >/dev/null 2>&1 || true
      printf "FRIEND_KEY=%s\n" "$FRIEND_KEY"
    else
      warn "sqlite INSERT failed — could not generate friend key."
    fi
  fi
fi

# 6. optional: ollama model pull. Keep this non-fatal — users with a
#    working z.ai / cloud-only setup don't need a local model, and a
#    misconfigured OLLAMA_MODELS (pointing at unmounted external
#    storage, etc.) should not abort the rest of the install.
LOCAL_MODEL_READY=0
if [ "$SKIP_OLLAMA" -eq 0 ] && command -v ollama >/dev/null; then
  printf "\033[1;36m▸\033[0m Pull a local coding model via ollama? [y/N] "
  read -r reply || reply="n"
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    say "Pulling qwen3-coder:30b (this can take a while — ~18GB)"
    if ollama pull qwen3-coder:30b; then
      LOCAL_MODEL_READY=1
    else
      warn "ollama pull failed. Check OLLAMA_MODELS and the path it points to."
    fi
  fi
fi

# 6.5 external provider — offered when no local model was configured
#     above AND the settings file does not already have an
#     llm_api_key. Add new providers by extending the PROVIDERS array.
if [ "$LOCAL_MODEL_READY" -eq 0 ]; then
  EXISTING_KEY="$(python3 -c "import json; print(json.load(open('$SETTINGS_FILE')).get('llm_api_key',''))" 2>/dev/null || true)"
  if [ -z "$EXISTING_KEY" ]; then
    # Provider catalogue: "<slug>|<label>|<llm_url>|<default_model>"
    PROVIDERS=(
      "zai|z.ai (GLM-5.1, Anthropic-compatible)|https://api.z.ai/api/paas/v4|glm-5.1"
    )
    printf "\033[1;36m▸\033[0m No local model configured. Pick an external provider?\n"
    idx=1
    for row in "${PROVIDERS[@]}"; do
      label="$(printf '%s' "$row" | cut -d'|' -f2)"
      printf "   (%d) %s\n" "$idx" "$label"
      idx=$((idx + 1))
    done
    printf "   (s) Skip (configure ~/.hermit/settings.json manually later)\n"
    printf "   [1/s]: "
    read -r provider_choice || provider_choice="s"
    provider_choice="$(echo "${provider_choice:-s}" | tr '[:upper:]' '[:lower:]')"

    case "$provider_choice" in
      s|skip|"")
        PENDING_STEPS+=("Set llm_url / llm_api_key / model in $SETTINGS_FILE, or pull an ollama model, to give Hermit an LLM to talk to.")
        ;;
      *)
        # Accept numeric choice only.
        if ! [[ "$provider_choice" =~ ^[0-9]+$ ]] || \
           [ "$provider_choice" -lt 1 ] || \
           [ "$provider_choice" -gt "${#PROVIDERS[@]}" ]; then
          warn "Unknown provider choice '$provider_choice' — skipping."
          PENDING_STEPS+=("Set llm_url / llm_api_key / model in $SETTINGS_FILE manually.")
        else
          row="${PROVIDERS[$((provider_choice - 1))]}"
          provider_label="$(printf '%s' "$row" | cut -d'|' -f2)"
          provider_url="$(printf '%s' "$row" | cut -d'|' -f3)"
          provider_model="$(printf '%s' "$row" | cut -d'|' -f4)"

          printf "   Paste your API key for %s (input hidden): " "$provider_label"
          read -rs api_key || api_key=""
          echo
          if [ -z "$api_key" ]; then
            warn "No API key entered — skipping."
            PENDING_STEPS+=("Add the $provider_label API key as llm_api_key in $SETTINGS_FILE when you have it.")
          else
            python3 - "$SETTINGS_FILE" "$provider_url" "$provider_model" "$api_key" <<'PYEOF'
import json, sys
path, url, model, key = sys.argv[1:5]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
data["llm_url"] = url
data["model"] = model
data["llm_api_key"] = key
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF
            say "Saved $provider_label credentials to $SETTINGS_FILE (model=$provider_model)."
          fi
        fi
        ;;
    esac
  fi
fi

# 7. symlink the -hermit slash commands into the user's Claude Code
#    config so `/feature-develop-hermit` etc. resolve. Symlinks (not
#    copies) mean `git pull` in this repo is picked up automatically.
USER_CC_COMMANDS="$HOME/.claude/commands"
mkdir -p "$USER_CC_COMMANDS"
for f in "$PROJECT_DIR"/.claude/commands/*-hermit.md; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  target="$USER_CC_COMMANDS/$name"
  if [ -L "$target" ] || [ ! -e "$target" ]; then
    ln -sf "$f" "$target"
    say "Linked $name → $USER_CC_COMMANDS/"
  else
    warn "Skipped $name — a regular file already exists at $target (not overwritten)."
  fi
done

# 7.5 optional: register the Hermit MCP server in ~/.claude.json so
#     Claude Code picks it up automatically. We never overwrite existing
#     non-Hermit entries, and re-runs of install.sh detect an identical
#     entry and skip (idempotent).
if [ "$SKIP_MCP_REGISTER" -eq 0 ]; then
  CLAUDE_JSON="$HOME/.claude.json"
  MCP_COMMAND="$PROJECT_DIR/bin/mcp-server.sh"
  printf "\033[1;36m▸\033[0m Register Hermit MCP server in ~/.claude.json?\n"
  printf "   (a) Project-specific — which project path? [default: %s]\n" "$PROJECT_DIR"
  printf "   (b) User-wide (all Claude Code sessions)\n"
  printf "   (c) Skip (register manually later)\n"
  printf "   [A/b/c]: "
  read -r mcp_choice || mcp_choice="c"
  mcp_choice="$(echo "${mcp_choice:-a}" | tr '[:upper:]' '[:lower:]')"

  case "$mcp_choice" in
    a|"")
      printf "   Project path [%s]: " "$PROJECT_DIR"
      read -r target_project || target_project=""
      target_project="${target_project:-$PROJECT_DIR}"
      # Normalize: expand ~ and make absolute
      target_project="$(eval echo "$target_project")"
      if [ ! -d "$target_project" ]; then
        warn "Project path does not exist: $target_project — skipping."
        PENDING_STEPS+=("Register Hermit MCP in ~/.claude.json manually (docs/cc-setup.md § 3).")
      else
        target_project="$(cd "$target_project" && pwd)"
        python3 - "$CLAUDE_JSON" "$target_project" "$MCP_COMMAND" project <<'PYEOF'
import json, os, shutil, sys
from datetime import datetime

path, target, command, scope = sys.argv[1:5]
entry = {"type": "stdio", "command": command}
name = "hermit-channel"

if os.path.exists(path):
    try:
        data = json.load(open(path))
    except json.JSONDecodeError:
        print(f"FAIL: {path} is not valid JSON. Leave it alone.", file=sys.stderr)
        sys.exit(2)
    # backup
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copyfile(path, f"{path}.backup-{ts}")
else:
    data = {}

if not isinstance(data, dict):
    print("FAIL: ~/.claude.json root is not an object.", file=sys.stderr)
    sys.exit(2)

projects = data.setdefault("projects", {})
proj = projects.setdefault(target, {})
mcp_servers = proj.setdefault("mcpServers", {})
existing = mcp_servers.get(name)
if existing == entry:
    print("UNCHANGED")
    sys.exit(0)

mcp_servers[name] = entry
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("REGISTERED")
PYEOF
        rc=$?
        if [ "$rc" = "0" ]; then
          say "Hermit MCP registered at project scope: $target_project"
          MCP_REGISTERED_BY_INSTALLER=1
        elif [ "$rc" = "2" ]; then
          warn "Could not update $CLAUDE_JSON (see message above)."
          PENDING_STEPS+=("Register Hermit MCP in $CLAUDE_JSON manually (docs/cc-setup.md § 3).")
        fi
      fi
      ;;
    b)
      python3 - "$CLAUDE_JSON" "$MCP_COMMAND" <<'PYEOF'
import json, os, shutil, sys
from datetime import datetime

path, command = sys.argv[1:3]
entry = {"type": "stdio", "command": command}
name = "hermit-channel"

if os.path.exists(path):
    try:
        data = json.load(open(path))
    except json.JSONDecodeError:
        print(f"FAIL: {path} is not valid JSON.", file=sys.stderr)
        sys.exit(2)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copyfile(path, f"{path}.backup-{ts}")
else:
    data = {}

if not isinstance(data, dict):
    print("FAIL: ~/.claude.json root is not an object.", file=sys.stderr)
    sys.exit(2)

mcp_servers = data.setdefault("mcpServers", {})
existing = mcp_servers.get(name)
if existing == entry:
    print("UNCHANGED")
    sys.exit(0)

mcp_servers[name] = entry
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("REGISTERED")
PYEOF
      rc=$?
      if [ "$rc" = "0" ]; then
        say "Hermit MCP registered user-wide in $CLAUDE_JSON"
        MCP_REGISTERED_BY_INSTALLER=1
      elif [ "$rc" = "2" ]; then
        warn "Could not update $CLAUDE_JSON (see message above)."
        PENDING_STEPS+=("Register Hermit MCP in $CLAUDE_JSON manually (docs/cc-setup.md § 3).")
      fi
      ;;
    *)
      PENDING_STEPS+=("Register Hermit MCP in ~/.claude.json (docs/cc-setup.md § 3).")
      ;;
  esac
  # Dev-channels flag reminder — we do not edit shell rc files.
  PENDING_STEPS+=("Start Claude Code with \`--dangerously-load-development-channels server:hermit-channel\` so CC loads the channel capability. (Shell alias example in README.)")
fi

# 7.75 optional: add `hermit` alias to the user's shell rc so they can
#      run `hermit` from anywhere without worrying about the path moving.
if [ "$SKIP_ALIAS" -eq 0 ]; then
  HERMIT_BIN="$PROJECT_DIR/bin/hermit.sh"

  # Detect shell rc: honour $SHELL first, then fall back by probing.
  RC_FILE=""
  case "${SHELL:-}" in
    */zsh)  [ -f "$HOME/.zshrc" ]  && RC_FILE="$HOME/.zshrc" ;;
    */bash) [ -f "$HOME/.bashrc" ] && RC_FILE="$HOME/.bashrc" ;;
  esac
  if [ -z "$RC_FILE" ]; then
    for candidate in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
      [ -f "$candidate" ] && { RC_FILE="$candidate"; break; }
    done
  fi

  if [ -z "$RC_FILE" ]; then
    PENDING_STEPS+=("No shell rc found — add manually: alias hermit=\"$HERMIT_BIN\"")
  else
    EXPECTED_LINE="alias hermit=\"$HERMIT_BIN\""
    # Any existing `alias hermit=` line? (tolerant of quoting and whitespace.)
    EXISTING_LINE="$(grep -n '^[[:space:]]*alias[[:space:]]\+hermit=' "$RC_FILE" | head -1 || true)"
    if [ -n "$EXISTING_LINE" ]; then
      EXISTING_TARGET="$(printf '%s' "$EXISTING_LINE" | sed -E 's/.*alias[[:space:]]+hermit=//' | tr -d "\"'" | sed -E 's/[[:space:]]+$//')"
      if [ "$EXISTING_TARGET" = "$HERMIT_BIN" ]; then
        say "hermit alias in $RC_FILE already points at $HERMIT_BIN — leaving it alone."
      else
        printf "\033[1;36m▸\033[0m hermit alias in %s points at %s.\n" "$RC_FILE" "$EXISTING_TARGET"
        printf "   Update it to %s? [Y/n] " "$HERMIT_BIN"
        read -r alias_reply || alias_reply="y"
        alias_reply="$(echo "${alias_reply:-y}" | tr '[:upper:]' '[:lower:]')"
        if [ "$alias_reply" = "y" ] || [ "$alias_reply" = "yes" ]; then
          LINE_NO="${EXISTING_LINE%%:*}"
          # Backup + in-place rewrite of just that line.
          cp "$RC_FILE" "$RC_FILE.backup-$(date +%Y%m%d-%H%M%S)"
          # Use a sed that is portable across BSD (macOS) and GNU.
          python3 - "$RC_FILE" "$LINE_NO" "$EXPECTED_LINE" <<'PYEOF'
import sys
path, line_no, new_line = sys.argv[1], int(sys.argv[2]), sys.argv[3]
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()
lines[line_no - 1] = new_line + "\n"
with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
PYEOF
          say "Updated hermit alias in $RC_FILE to $HERMIT_BIN"
          PENDING_STEPS+=("Run \`source $RC_FILE\` (or restart your shell) to pick up the updated hermit alias.")
        else
          PENDING_STEPS+=("Existing hermit alias points at stale path — update manually: $EXPECTED_LINE")
        fi
      fi
    else
      printf "\033[1;36m▸\033[0m Add \`hermit\` alias to %s? [Y/n] " "$RC_FILE"
      read -r alias_reply || alias_reply="y"
      alias_reply="$(echo "${alias_reply:-y}" | tr '[:upper:]' '[:lower:]')"
      if [ "$alias_reply" = "y" ] || [ "$alias_reply" = "yes" ]; then
        {
          printf "\n# Added by hermit-agent install.sh\n"
          printf "%s\n" "$EXPECTED_LINE"
        } >> "$RC_FILE"
        say "Added hermit alias to $RC_FILE"
        PENDING_STEPS+=("Run \`source $RC_FILE\` (or restart your shell) to pick up the hermit alias.")
      else
        PENDING_STEPS+=("Add manually: $EXPECTED_LINE")
      fi
    fi
  fi
fi

# 8. sanity check
say "Sanity check — importing hermit_agent"
"$VENV_PY" -c 'import hermit_agent; print("  version:", hermit_agent.__version__ if hasattr(hermit_agent, "__version__") else "dev")'

say "Done. Next steps:"
echo "  1. Start the gateway:  ./bin/gateway.sh --daemon  (auto-started by \`hermit\` too)"
if [ "$MCP_REGISTERED_BY_INSTALLER" -eq 1 ]; then
  echo "  2. Launch Claude Code with \`--dangerously-load-development-channels server:hermit-channel\`"
  echo "     then try /feature-develop-hermit <task>. See docs/hermit-variants.md for more skills."
else
  echo "  2. Register MCP server in Claude Code — see docs/cc-setup.md"
  echo "  3. In Claude Code, try one of the bundled reference skills"
  echo "     (e.g. /feature-develop-hermit <task>), or read"
  echo "     docs/hermit-variants.md and fork your own."
fi

if [ ${#PENDING_STEPS[@]} -gt 0 ]; then
  echo
  warn "Pending manual steps (install skipped these):"
  for step in "${PENDING_STEPS[@]}"; do
    echo "   - $step"
  done
fi
