import { readFile, writeFile, mkdir, access } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { spawn } from "node:child_process";

export const NPM_PACKAGE_NAME = "@cafitac/hermit-agent";
const UPDATE_TTL_MS = 24 * 60 * 60 * 1000;
const packageJsonUrl = new URL("../../package.json", import.meta.url);

export async function readCurrentVersion() {
  const raw = await readFile(packageJsonUrl, "utf8");
  const parsed = JSON.parse(raw);
  return parsed.version ?? "0.0.0";
}

export function resolveUpdateStateFile(customPath = process.env.HERMIT_UPDATE_STATE_FILE) {
  return customPath ?? resolve(homedir(), ".hermit", "npm-runtime", "update-state.json");
}

export async function readUpdateState(stateFile = resolveUpdateStateFile()) {
  try {
    const raw = await readFile(stateFile, "utf8");
    return JSON.parse(raw);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return {};
    }
    throw error;
  }
}

export async function writeUpdateState(state, stateFile = resolveUpdateStateFile()) {
  await mkdir(dirname(stateFile), { recursive: true });
  await writeFile(stateFile, JSON.stringify(state, null, 2) + "\n", "utf8");
}

export function compareVersions(left, right) {
  const normalize = (value) => value.split("-")[0]?.split(".").map((part) => Number.parseInt(part, 10) || 0) ?? [0];
  const leftParts = normalize(left);
  const rightParts = normalize(right);
  const width = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < width; index += 1) {
    const a = leftParts[index] ?? 0;
    const b = rightParts[index] ?? 0;
    if (a > b) return 1;
    if (a < b) return -1;
  }
  return 0;
}

export function shouldCheckForUpdates(state, now = Date.now()) {
  if (!state.lastCheckedAt) return true;
  const lastCheckedAt = Date.parse(state.lastCheckedAt);
  if (Number.isNaN(lastCheckedAt)) return true;
  return now - lastCheckedAt >= UPDATE_TTL_MS;
}

export async function detectInstallContext() {
  const packageRoot = dirname(fileURLToPath(packageJsonUrl));
  const repoGitDir = resolve(packageRoot, ".git");
  try {
    await access(repoGitDir, constants.F_OK);
    return "source-checkout";
  } catch {
    return "published-package";
  }
}

export async function fetchLatestVersion() {
  const response = await fetch(`https://registry.npmjs.org/${encodeURIComponent(NPM_PACKAGE_NAME)}/latest`, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`failed to check npm registry: ${response.status}`);
  }
  const payload = await response.json();
  if (!payload.version) {
    throw new Error("npm registry payload did not include version");
  }
  return payload.version;
}

export async function checkForUpdates({ force = false } = {}) {
  const stateFile = resolveUpdateStateFile();
  const currentVersion = await readCurrentVersion();
  const state = await readUpdateState(stateFile);
  if (!force && !shouldCheckForUpdates(state)) {
    return null;
  }
  const latestVersion = await fetchLatestVersion();
  const checkedAt = new Date().toISOString();
  await writeUpdateState({ ...state, lastCheckedAt: checkedAt }, stateFile);
  if (compareVersions(latestVersion, currentVersion) <= 0) {
    return null;
  }
  return {
    currentVersion,
    latestVersion,
    stateFile,
    installContext: await detectInstallContext(),
  };
}

export function formatUpdateCommand() {
  return `npm install -g ${NPM_PACKAGE_NAME}@latest`;
}

export function buildUpdateHintLines(availability) {
  if (availability.installContext === "source-checkout") {
    return [
      `[HERMIT] Update available: v${availability.currentVersion} -> v${availability.latestVersion}`,
      "[HERMIT] Source checkout detected. Pull latest changes and republish/reinstall locally.",
    ];
  }
  return [
    `[HERMIT] Update available: v${availability.currentVersion} -> v${availability.latestVersion}`,
    `[HERMIT] Run: hermit self-update`,
  ];
}

export async function runSelfUpdate() {
  const installContext = await detectInstallContext();
  if (installContext === "source-checkout") {
    return {
      ok: false,
      message: "Source checkout detected. Update the repo directly instead of using hermit self-update.",
    };
  }

  const child = spawn("npm", ["install", "-g", `${NPM_PACKAGE_NAME}@latest`], {
    stdio: "inherit",
    shell: process.platform === "win32",
  });

  const exitCode = await new Promise((resolve) => child.once("exit", resolve));
  if (exitCode !== 0) {
    return { ok: false, message: "self-update failed" };
  }
  return {
    ok: true,
    message: `Updated ${NPM_PACKAGE_NAME}. Re-run hermit if you want the refreshed wrapper/runtime.`,
  };
}
