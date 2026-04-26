#!/usr/bin/env node
// Thin launcher — lets npm bin resolve to this file while dist/app.js
// has no shebang (it is compiled output from tsc).
import { spawn, spawnSync } from 'child_process';
import { existsSync, openSync, closeSync, readFileSync, readSync, writeSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { homedir } from 'os';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appJs = join(__dirname, '..', 'dist', 'app.js');

const rawArgs = process.argv.slice(2);
const command = rawArgs[0] ?? '';
const packageName = '@cafitac/hermit-agent';

function runtimeHome() {
  return process.env.HERMIT_HOME || homedir();
}

function readCurrentPackageVersion() {
  const pkg = JSON.parse(readFileSync(join(__dirname, '..', 'package.json'), 'utf8'));
  return String(pkg.version ?? '').trim();
}

function readInstalledGlobalVersion() {
  const result = spawnSync(
    'npm',
    ['list', '-g', packageName, '--json', '--depth=0'],
    {
      encoding: 'utf8',
      shell: process.platform === 'win32',
    },
  );

  const stdout = String(result.stdout ?? '').trim();
  if (!stdout) return null;

  try {
    const payload = JSON.parse(stdout);
    const version = payload?.dependencies?.[packageName]?.version;
    if (typeof version === 'string' && version.trim()) return version.trim();
  } catch {
    return null;
  }
  return null;
}

function readManagedRuntimeVersion(venvPython) {
  if (!existsSync(venvPython)) return null;
  const result = spawnSync(
    venvPython,
    [
      '-c',
      'import importlib.metadata as m; print(m.version("cafitac-hermit-agent"))',
    ],
    {
      encoding: 'utf8',
      shell: process.platform === 'win32',
    },
  );
  if (result.status !== 0) return null;
  const version = String(result.stdout ?? '').trim();
  return version || null;
}

function isInteractivePromptAllowed() {
  if (process.env.HERMIT_SKIP_STARTUP_UPDATE_CHECK === '1') return false;
  if (process.env.HERMIT_FORCE_STARTUP_PROMPTS === '1') return true;
  return Boolean(process.stdin.isTTY && process.stdout.isTTY);
}

function shouldPromptForUpdate(commandName) {
  if (!isInteractivePromptAllowed()) return false;
  if (!commandName) return true;
  return !['help', 'version', 'update', 'self-update', 'mcp-server'].includes(commandName);
}

function promptYesNo(question, defaultYes = true) {
  if (!isInteractivePromptAllowed()) return false;
  const suffix = defaultYes ? ' [Y/n] ' : ' [y/N] ';
  const prompt = `${question}${suffix}`;
  let inputFd = null;
  try {
    inputFd = openSync('/dev/tty', 'r');
  } catch {
    inputFd = null;
  }

  try {
    writeSync(process.stdout.fd, prompt);
    const buffer = Buffer.alloc(1024);
    const bytesRead = readSync(inputFd ?? process.stdin.fd, buffer, 0, buffer.length, null);
    const answer = buffer.toString('utf8', 0, Math.max(0, bytesRead)).trim().toLowerCase();
    if (!answer) return defaultYes;
    return answer === 'y' || answer === 'yes';
  } catch (error) {
    if (error && (error.code === 'EAGAIN' || error.code === 'EWOULDBLOCK')) {
      writeSync(process.stdout.fd, '\n');
      return defaultYes;
    }
    throw error;
  } finally {
    if (inputFd !== null) closeSync(inputFd);
  }
}

function readLatestPublishedVersion() {
  const result = spawnSync(
    'npm',
    ['view', packageName, 'version', '--json'],
    {
      encoding: 'utf8',
      shell: process.platform === 'win32',
    },
  );

  if (result.status !== 0) return null;
  const stdout = String(result.stdout ?? '').trim();
  if (!stdout) return null;

  try {
    const payload = JSON.parse(stdout);
    if (typeof payload === 'string' && payload.trim()) return payload.trim();
  } catch {
    if (stdout) return stdout.replace(/^"+|"+$/g, '').trim() || null;
  }
  return null;
}

function compareVersions(left, right) {
  const leftParts = String(left || '').split('.').map(part => Number.parseInt(part, 10) || 0);
  const rightParts = String(right || '').split('.').map(part => Number.parseInt(part, 10) || 0);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let idx = 0; idx < length; idx += 1) {
    const a = leftParts[idx] ?? 0;
    const b = rightParts[idx] ?? 0;
    if (a > b) return 1;
    if (a < b) return -1;
  }
  return 0;
}

function maybePromptForSelfUpdate(commandName) {
  if (!shouldPromptForUpdate(commandName)) return false;

  const currentVersion = readCurrentPackageVersion();
  const latestVersion = readLatestPublishedVersion();
  if (!latestVersion || compareVersions(latestVersion, currentVersion) <= 0) return false;
  if (!promptYesNo(`[hermit] A newer version is available (v${currentVersion} -> v${latestVersion}). Update before continuing?`)) {
    return false;
  }

  runSelfUpdate();
  return true;
}

function runSelfUpdate() {
  const beforeVersion = readCurrentPackageVersion();
  const install = spawnSync(
    'npm',
    ['install', '-g', `${packageName}@latest`],
    {
      stdio: 'inherit',
      shell: process.platform === 'win32',
    },
  );

  if (install.status !== 0) {
    process.exit(install.status ?? 1);
  }

  const afterVersion = readInstalledGlobalVersion();
  syncManagedRuntime(afterVersion || beforeVersion);
  if (!afterVersion) {
    console.log(`[hermit] Update complete. Current installed version: v${beforeVersion}`);
    process.exit(0);
  }

  if (afterVersion === beforeVersion) {
    console.log(`[hermit] Already using the latest version (v${afterVersion}).`);
    process.exit(0);
  }

  console.log(`[hermit] Updated from v${beforeVersion} to v${afterVersion}.`);
  process.exit(0);
}

// --- Meta commands (no Python or TUI needed) ---

if (command === 'version' || rawArgs.includes('--version') || rawArgs.includes('-v')) {
  console.log(readCurrentPackageVersion());
  process.exit(0);
}

if (command === 'help' || rawArgs.includes('--help') || rawArgs.includes('-h')) {
  console.log(`hermit v${readCurrentPackageVersion()} — Local LLM Coding Agent

Usage:
  hermit                        Interactive TUI (default)
  hermit "<message>"            Single message (CLI mode)
  hermit <command> [options]

Commands:
  install                       Guided setup / install flow (Claude + Codex)
  mcp-server                    Start the Hermit MCP server over stdio
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

function findInVenv(...names) {
  const home = runtimeHome();
  const venvBin = join(home, '.hermit', 'npm-runtime', 'venv', 'bin');
  const venvScripts = join(home, '.hermit', 'npm-runtime', 'venv', 'Scripts');
  for (const name of names) {
    for (const dir of [venvBin, venvScripts]) {
      const p = join(dir, name);
      if (existsSync(p)) return p;
    }
  }
  return null;
}

function findPythonBin() {
  return process.env.HERMIT_PYTHON || findInVenv('hermit', 'hermit.exe');
}

function findVenvPython() {
  return process.env.HERMIT_PYTHON || findInVenv('python', 'python3', 'python.exe');
}

function syncManagedRuntime(expectedVersion) {
  if (process.env.HERMIT_SKIP_MANAGED_RUNTIME_SYNC === '1') return;
  const venvPython = findVenvPython();
  if (!venvPython || !existsSync(venvPython) || !expectedVersion) return;

  const managedVersion = readManagedRuntimeVersion(venvPython);
  if (managedVersion === expectedVersion) return;

  const pip = join(dirname(venvPython), process.platform === 'win32' ? 'pip.exe' : 'pip');
  if (!existsSync(pip)) return;

  console.log(`[hermit] Syncing managed runtime to v${expectedVersion}...`);
  const install = spawnSync(
    pip,
    ['install', '--quiet', '--upgrade', `cafitac-hermit-agent==${expectedVersion}`],
    { stdio: 'inherit' },
  );
  if (install.status !== 0) {
    console.error(`[hermit] Failed to sync managed runtime to v${expectedVersion}.`);
    process.exit(install.status ?? 1);
  }
}

function spawnAndExit(cmd, args, opts = {}) {
  const child = spawn(cmd, args, { stdio: 'inherit', ...opts });
  child.on('exit', code => process.exit(code ?? 0));
}

function bootstrapRuntime() {
  const home = runtimeHome();
  const venvDir = join(home, '.hermit', 'npm-runtime', 'venv');
  const venvPython = join(venvDir, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python3');

  if (existsSync(venvPython)) {
    syncManagedRuntime(readCurrentPackageVersion());
    return; // already set up
  }

  console.log('[hermit] First run: setting up Python runtime...');

  // Find a suitable system Python 3
  const candidates = process.platform === 'win32'
    ? ['python', 'python3']
    : ['python3', 'python'];
  let sysPython = null;
  for (const name of candidates) {
    const r = spawnSync(name, ['--version'], { encoding: 'utf8' });
    if (r.status === 0 && /Python 3/.test(r.stdout + r.stderr)) {
      sysPython = name;
      break;
    }
  }
  if (!sysPython) {
    console.error('[hermit] Python 3 not found. Please install Python 3.9+ and re-run.');
    process.exit(1);
  }

  // Create venv
  console.log('[hermit] Creating venv at ~/.hermit/npm-runtime/venv ...');
  const mkVenv = spawnSync(sysPython, ['-m', 'venv', venvDir], { stdio: 'inherit' });
  if (mkVenv.status !== 0) {
    console.error('[hermit] Failed to create venv.');
    process.exit(1);
  }

  // Install hermit Python package
  const pip = join(venvDir, process.platform === 'win32' ? 'Scripts/pip' : 'bin/pip');
  console.log('[hermit] Installing cafitac-hermit-agent...');
  const install = spawnSync(pip, ['install', '--quiet', 'cafitac-hermit-agent'], { stdio: 'inherit' });
  if (install.status !== 0) {
    console.error('[hermit] Failed to install cafitac-hermit-agent.');
    process.exit(1);
  }
  console.log('[hermit] Runtime ready.\n');
}

if (command === 'update' || command === 'self-update') {
  runSelfUpdate();
} else if (command && !command.startsWith('-')) {
  if (maybePromptForSelfUpdate(command)) {
    process.exit(0);
  }
  // Non-flag first argument: subcommand or single message → Python backend
  bootstrapRuntime();
  const pythonBin = findPythonBin();
  if (pythonBin) {
    spawnAndExit(pythonBin, rawArgs);
  } else {
    console.error('[hermit] Python runtime not found. Run: hermit install');
    process.exit(1);
  }
} else {
  // No args (or only flags) → interactive TUI
  if (maybePromptForSelfUpdate(command)) {
    process.exit(0);
  }
  bootstrapRuntime();
  // Set HERMIT_PYTHON so the TUI uses the managed venv, not the system Python.
  const venvPython = findVenvPython();
  const tuiEnv = venvPython ? { ...process.env, HERMIT_PYTHON: venvPython } : process.env;
  spawnAndExit(process.execPath, [appJs, ...rawArgs], { env: tuiEnv });
}
