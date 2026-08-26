#!/usr/bin/env node
// Minimal npm launcher for the Python MCP executor.
import { existsSync } from 'fs';
import { homedir } from 'os';
import { dirname, join } from 'path';
import { spawn, spawnSync } from 'child_process';
import { fileURLToPath } from 'url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(await import('fs').then(({readFileSync}) => readFileSync(join(root, 'package.json'), 'utf8')));
const version = String(pkg.version);
const args = process.argv.slice(2);
const home = process.env.HERMIT_HOME || homedir();
const venv = join(home, '.hermit', 'npm-runtime', 'venv');
const windows = process.platform === 'win32';
const python = join(venv, windows ? 'Scripts/python.exe' : 'bin/python3');
const hermit = join(venv, windows ? 'Scripts/hermit.exe' : 'bin/hermit');

function usage() {
  console.log(`hermit v${version} — MCP coding executor

Usage:
  hermit install claude
  hermit install codex
  hermit mcp-server
  hermit doctor`);
}

function bootstrap() {
  if (existsSync(python) && existsSync(hermit)) return;
  const candidates = windows ? ['python', 'python3'] : ['python3', 'python'];
  const systemPython = candidates.find(candidate => spawnSync(candidate, ['--version']).status === 0);
  if (!systemPython) {
    console.error('[hermit] Python 3.11+ is required. Install it and run this command again.');
    process.exit(1);
  }
  console.error('[hermit] Installing the MCP runtime…');
  if (spawnSync(systemPython, ['-m', 'venv', venv], {stdio: 'inherit'}).status !== 0) process.exit(1);
  const pip = join(venv, windows ? 'Scripts/pip.exe' : 'bin/pip');
  if (spawnSync(pip, ['install', '--quiet', `cafitac-hermit-agent==${version}`], {stdio: 'inherit'}).status !== 0) process.exit(1);
}

if (!args.length || args.includes('--help') || args.includes('-h')) {
  usage();
  process.exit(0);
}
if (args.includes('--version') || args.includes('-v') || args[0] === 'version') {
  console.log(version);
  process.exit(0);
}
bootstrap();
const child = spawn(hermit, args, {stdio: 'inherit'});
child.on('exit', code => process.exit(code ?? 1));
