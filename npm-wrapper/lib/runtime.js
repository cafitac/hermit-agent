import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";

export const DEFAULT_PYPI_SPEC = "cafitac-hermit-agent";
const packageJsonPath = new URL("../../package.json", import.meta.url);
const packageRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);

export function getHermitHome(env = process.env) {
  return env.HERMIT_HOME || path.join(os.homedir(), ".hermit");
}

export function getRuntimeLayout({
  platform = process.platform,
  hermitHome = getHermitHome(),
} = {}) {
  const scriptsDir = platform === "win32" ? "Scripts" : "bin";
  const launcherName = platform === "win32" ? "hermit.exe" : "hermit";
  const gatewayLauncherName = platform === "win32" ? "hermit-gateway.exe" : "hermit-gateway";
  const pythonName = platform === "win32" ? "python.exe" : "python";
  const runtimeRoot = path.join(hermitHome, "npm-runtime");
  const venvDir = path.join(runtimeRoot, "venv");
  return {
    runtimeRoot,
    venvDir,
    installMetaPath: path.join(runtimeRoot, "install-meta.json"),
    launcherPath: path.join(venvDir, scriptsDir, launcherName),
    gatewayLauncherPath: path.join(venvDir, scriptsDir, gatewayLauncherName),
    pythonPath: path.join(venvDir, scriptsDir, pythonName),
  };
}

export function resolvePackagedUiEntry(fsImpl = fs) {
  const uiEntry = path.join(packageRoot, "hermit-ui", "dist", "app.js");
  return fsImpl.existsSync(uiEntry) ? uiEntry : null;
}

export function shouldLaunchInteractiveUi({
  args,
  stdoutIsTTY,
  stdinIsTTY,
  uiEntry,
}) {
  return args.length === 0 && stdoutIsTTY && stdinIsTTY && Boolean(uiEntry);
}

export async function probeGatewayHealth(baseUrl = process.env.HERMIT_GATEWAY_URL || "http://127.0.0.1:8765") {
  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function ensureGatewayForUi({
  env = process.env,
  layout,
  fsImpl = fs,
  spawnImpl = spawn,
  waitMs = 5000,
}) {
  const autoGateway = String(env.HERMIT_AUTO_GATEWAY ?? "1").trim().toLowerCase();
  if (["0", "false", "no"].includes(autoGateway)) {
    return;
  }
  if (await probeGatewayHealth(env.HERMIT_GATEWAY_URL)) {
    return;
  }
  if (!fsImpl.existsSync(layout.gatewayLauncherPath)) {
    return;
  }

  spawnImpl(layout.gatewayLauncherPath, [], {
    stdio: "ignore",
    env,
    detached: true,
  }).unref?.();

  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    if (await probeGatewayHealth(env.HERMIT_GATEWAY_URL)) {
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
}

export function buildInteractiveUiEnv({
  env = process.env,
  layout,
}) {
  return {
    ...env,
    HERMIT_PYTHON: layout.pythonPath,
    HERMIT_VENV_DIR: layout.venvDir,
    HERMIT_DIR: packageRoot,
  };
}

export function getPythonCandidates({
  platform = process.platform,
  env = process.env,
} = {}) {
  if (env.HERMIT_PYTHON) {
    return [{ command: env.HERMIT_PYTHON, args: [] }];
  }
  if (platform === "win32") {
    return [
      { command: "py", args: ["-3"] },
      { command: "python3", args: [] },
      { command: "python", args: [] },
    ];
  }
  return [
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ];
}

export function findPythonCommand({
  platform = process.platform,
  env = process.env,
  spawnSyncImpl = spawnSync,
} = {}) {
  for (const candidate of getPythonCandidates({ platform, env })) {
    const probe = spawnSyncImpl(candidate.command, [...candidate.args, "--version"], {
      stdio: "ignore",
    });
    if (probe.status === 0) {
      return candidate;
    }
  }
  return null;
}

export function readInstallMeta(layout, fsImpl = fs) {
  try {
    return JSON.parse(fsImpl.readFileSync(layout.installMetaPath, "utf8"));
  } catch {
    return null;
  }
}

export async function readWrapperVersion() {
  const raw = await readFile(packageJsonPath, "utf8");
  const parsed = JSON.parse(raw);
  return parsed.version ?? "0.0.0";
}

export function needsBootstrap({
  layout,
  packageSpec,
  wrapperVersion,
  fsImpl = fs,
}) {
  if (!fsImpl.existsSync(layout.launcherPath)) {
    return true;
  }
  const meta = readInstallMeta(layout, fsImpl);
  return meta?.packageSpec !== packageSpec || meta?.wrapperVersion !== wrapperVersion;
}

export function buildBootstrapPlan({
  pythonCommand,
  layout,
  packageSpec,
}) {
  return [
    { command: pythonCommand.command, args: [...pythonCommand.args, "-m", "venv", layout.venvDir] },
    { command: layout.pythonPath, args: ["-m", "pip", "install", "--upgrade", "pip"] },
    { command: layout.pythonPath, args: ["-m", "pip", "install", packageSpec] },
  ];
}

export function writeInstallMeta({
  layout,
  packageSpec,
  wrapperVersion,
  fsImpl = fs,
}) {
  fsImpl.mkdirSync(layout.runtimeRoot, { recursive: true });
  fsImpl.writeFileSync(
    layout.installMetaPath,
    JSON.stringify({ packageSpec, wrapperVersion }, null, 2) + "\n",
    "utf8",
  );
}

export function bootstrapRuntime({
  env = process.env,
  platform = process.platform,
  fsImpl = fs,
  spawnSyncImpl = spawnSync,
  wrapperVersion = "0.0.0",
} = {}) {
  const packageSpec = env.HERMIT_NPM_PYPI_SPEC || DEFAULT_PYPI_SPEC;
  const layout = getRuntimeLayout({ platform, hermitHome: getHermitHome(env) });

  if (!needsBootstrap({ layout, packageSpec, wrapperVersion, fsImpl })) {
    return layout;
  }

  const pythonCommand = findPythonCommand({ platform, env, spawnSyncImpl });
  if (!pythonCommand) {
    throw new Error("python3 was not found. Install Python 3.11+ first.");
  }

  fsImpl.mkdirSync(layout.runtimeRoot, { recursive: true });
  for (const step of buildBootstrapPlan({ pythonCommand, layout, packageSpec })) {
    const result = spawnSyncImpl(step.command, step.args, { stdio: "inherit" });
    if (result.status !== 0) {
      throw new Error(`bootstrap command failed: ${step.command} ${step.args.join(" ")}`);
    }
  }
  writeInstallMeta({ layout, packageSpec, wrapperVersion, fsImpl });
  return layout;
}

export function spawnHermit({
  args,
  env = process.env,
  platform = process.platform,
  fsImpl = fs,
  spawnImpl = spawn,
  spawnSyncImpl = spawnSync,
  wrapperVersion = "0.0.0",
  stdoutIsTTY = Boolean(process.stdout.isTTY),
  stdinIsTTY = Boolean(process.stdin.isTTY),
}) {
  const layout = bootstrapRuntime({ env, platform, fsImpl, spawnSyncImpl, wrapperVersion });
  const uiEntry = resolvePackagedUiEntry(fsImpl);

  const spawnChild = async () => {
    if (
      shouldLaunchInteractiveUi({
        args,
        stdoutIsTTY,
        stdinIsTTY,
        uiEntry,
      })
    ) {
      await ensureGatewayForUi({ env, layout, fsImpl, spawnImpl });
      return spawnImpl("node", [uiEntry], {
        stdio: "inherit",
        env: buildInteractiveUiEnv({ env, layout }),
      });
    }

    return spawnImpl(layout.launcherPath, args, {
      stdio: "inherit",
      env,
    });
  };

  return spawnChild().then(child => {
    child.on("exit", (code, signal) => {
      if (signal) {
        process.kill(process.pid, signal);
        return;
      }
      process.exit(code ?? 1);
    });
    return child;
  });
}
