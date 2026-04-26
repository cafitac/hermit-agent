#!/usr/bin/env node
// Thin launcher — lets npm bin resolve to this file while dist/app.js
// has no shebang (it is compiled output from tsc).
import { spawn } from 'child_process';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appJs = join(__dirname, '..', 'dist', 'app.js');

const rawArgs = process.argv.slice(2);
const command = rawArgs[0] ?? '';

if (command === 'version' || rawArgs.includes('--version') || rawArgs.includes('-v')) {
  const pkg = JSON.parse(readFileSync(join(__dirname, '..', 'package.json'), 'utf8'));
  console.log(pkg.version);
  process.exit(0);
}

if (command === 'help' || rawArgs.includes('--help') || rawArgs.includes('-h')) {
  const pkg = JSON.parse(readFileSync(join(__dirname, '..', 'package.json'), 'utf8'));
  console.log(`hermit v${pkg.version} — Local LLM Coding Agent

Usage:
  hermit                        Interactive TUI (default)
  hermit "<message>"            Single message (CLI mode)
  hermit <command> [options]

Commands:
  install                       Guided setup / install flow
  setup-claude                  Prepare Hermit's Claude Code integration
  setup-codex                   Prepare Hermit's Codex integration
  doctor                        Diagnose and repair common setup issues
  status                        Show agent / gateway status
  config local-backend          Detect or set local LLM backend (mlx, llama.cpp, ollama)
  update, self-update           Update hermit to the latest version
  version                       Show version number
  help                          Show this help message

Agent options (single-message mode):
  --model <name>                Model to use
  --base-url <url>              API base URL (default: http://localhost:8765/v1)
  --api-key <key>               Bearer token for the gateway
  --yolo                        Skip all permission checks
  --ask                         Ask permission for every tool call
  --accept-edits                Auto-allow reads+edits, ask for bash
  --dont-ask                    Allow everything silently with logging
  --plan                        Read-only mode (block all writes)
  --channel <cli|none>          Channel interface
  --no-stream                   Disable streaming output
  --max-turns <n>               Max agent turns (default: 50)
  --max-context <n>             Max context tokens (default: 32000)
  --fallback-model <name>       Fallback model after repeated failures

Startup flags:
  --version, -v                 Show version number
  --help, -h                    Show this help message`);
  process.exit(0);
}

if (command === 'update' || command === 'self-update') {
  const child = spawn('npm', ['install', '-g', '@cafitac/hermit-agent@latest'], { stdio: 'inherit', shell: process.platform === 'win32' });
  child.on('exit', code => process.exit(code ?? 0));
} else {
  const child = spawn(process.execPath, [appJs, ...rawArgs], { stdio: 'inherit' });
  child.on('exit', code => process.exit(code ?? 0));
}
