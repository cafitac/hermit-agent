import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

export const DEFAULT_PYPI_SPEC = "cafitac-hermit-agent";

export function getHermitHome(env = process.env) {
  return env.HERMIT_HOME || path.join(os.homedir(), ".hermit");
}

export function getRuntimeLayout({
  platform = process.platform,
  hermitHome = getHermitHome(),
} = {}) {
  const scriptsDir = platform === "win32" ? "Scripts" : "bin";
  const launcherName = platform === "win32" ? "hermit.exe" : "hermit";
  const pythonName = platform === "win32" ? "python.exe" : "python";
  const runtimeRoot = path.join(hermitHome, "npm-runtime");
  const venvDir = path.join(runtimeRoot, "venv");
  return {
    runtimeRoot,
    venvDir,
    installMetaPath: path.join(runtimeRoot, "install-meta.json"),
    launcherPath: path.join(venvDir, scriptsDir, launcherName),
    pythonPath: path.join(venvDir, scriptsDir, pythonName),
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

export function needsBootstrap({
  layout,
  packageSpec,
  fsImpl = fs,
}) {
  if (!fsImpl.existsSync(layout.launcherPath)) {
    return true;
  }
  const meta = readInstallMeta(layout, fsImpl);
  return meta?.packageSpec !== packageSpec;
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
  fsImpl = fs,
}) {
  fsImpl.mkdirSync(layout.runtimeRoot, { recursive: true });
  fsImpl.writeFileSync(
    layout.installMetaPath,
    JSON.stringify({ packageSpec }, null, 2) + "\n",
    "utf8",
  );
}

export function bootstrapRuntime({
  env = process.env,
  platform = process.platform,
  fsImpl = fs,
  spawnSyncImpl = spawnSync,
} = {}) {
  const packageSpec = env.HERMIT_NPM_PYPI_SPEC || DEFAULT_PYPI_SPEC;
  const layout = getRuntimeLayout({ platform, hermitHome: getHermitHome(env) });

  if (!needsBootstrap({ layout, packageSpec, fsImpl })) {
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
  writeInstallMeta({ layout, packageSpec, fsImpl });
  return layout;
}

export function spawnHermit({
  args,
  env = process.env,
  platform = process.platform,
  fsImpl = fs,
  spawnImpl = spawn,
  spawnSyncImpl = spawnSync,
}) {
  const layout = bootstrapRuntime({ env, platform, fsImpl, spawnSyncImpl });
  const child = spawnImpl(layout.launcherPath, args, {
    stdio: "inherit",
    env,
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
  return child;
}
