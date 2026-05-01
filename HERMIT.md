# HermitAgent Project Configuration

## Project Overview
- Claude Code source analysis + HermitAgent coding agent implementation project
- Python 3.13, minimal external dependencies

## Directory Structure
```
hermit-agent/
├── hermit_agent/     # HermitAgent agent package (Python)
├── bin/              # launchers: gateway.sh, mcp-server.sh, hermit.sh
├── tests/            # tests
├── src/              # Claude Code original source (read-only, modifications prohibited)
├── docs/             # architecture analysis docs
├── scripts/          # demo / benchmark / harness helpers
└── pyproject.toml    # package configuration
```

## Rules
- `src/` directory: absolutely no modifications or additions
- New projects in a separate directory (do not create Django/React projects inside this repo)
- HermitAgent code modifications only within `hermit_agent/`

## Build/Test
```bash
# Python tests (uses project-local .venv by default; override with HERMIT_VENV_DIR)
.venv/bin/python -m pytest tests/

# Run via launcher (CLI or TUI)
./bin/hermit.sh "your message"    # single-message CLI mode
./bin/hermit.sh                    # interactive TUI (requires HERMIT_UI_DIR or co-located UI)
```
