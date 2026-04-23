import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_PYPI_SPEC,
  buildBootstrapPlan,
  buildInteractiveUiEnv,
  findPythonCommand,
  getPythonCandidates,
  getRuntimeLayout,
  needsBootstrap,
  resolvePackagedUiEntry,
  spawnHermit,
  shouldLaunchInteractiveUi,
} from "../lib/runtime.js";

test("runtime layout uses ~/.hermit/npm-runtime by default", () => {
  const layout = getRuntimeLayout({ platform: "darwin", hermitHome: "/tmp/hermit-home" });
  assert.equal(layout.runtimeRoot, "/tmp/hermit-home/npm-runtime");
  assert.equal(layout.venvDir, "/tmp/hermit-home/npm-runtime/venv");
  assert.equal(layout.launcherPath, "/tmp/hermit-home/npm-runtime/venv/bin/hermit");
  assert.equal(layout.gatewayLauncherPath, "/tmp/hermit-home/npm-runtime/venv/bin/hermit-gateway");
  assert.equal(layout.pythonPath, "/tmp/hermit-home/npm-runtime/venv/bin/python");
});

test("python candidates prefer python3 on unix and py -3 on windows", () => {
  assert.deepEqual(getPythonCandidates({ platform: "linux", env: {} }), [
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ]);
  assert.deepEqual(getPythonCandidates({ platform: "win32", env: {} }), [
    { command: "py", args: ["-3"] },
    { command: "python3", args: [] },
    { command: "python", args: [] },
  ]);
});

test("findPythonCommand returns the first working candidate", () => {
  const seen = [];
  const result = findPythonCommand({
    platform: "linux",
    env: {},
    spawnSyncImpl(command, args) {
      seen.push([command, ...args]);
      return { status: command === "python3" ? 0 : 1 };
    },
  });
  assert.deepEqual(seen[0], ["python3", "--version"]);
  assert.deepEqual(result, { command: "python3", args: [] });
});

test("bootstrap plan installs the published Python package into the managed venv", () => {
  const layout = getRuntimeLayout({ platform: "linux", hermitHome: "/tmp/hermit-home" });
  const plan = buildBootstrapPlan({
    pythonCommand: { command: "python3", args: [] },
    layout,
    packageSpec: DEFAULT_PYPI_SPEC,
  });
  assert.deepEqual(plan, [
    { command: "python3", args: ["-m", "venv", "/tmp/hermit-home/npm-runtime/venv"] },
    { command: "/tmp/hermit-home/npm-runtime/venv/bin/python", args: ["-m", "pip", "install", "--upgrade", "pip"] },
    { command: "/tmp/hermit-home/npm-runtime/venv/bin/python", args: ["-m", "pip", "install", "cafitac-hermit-agent"] },
  ]);
});

test("needsBootstrap returns false only when launcher exists and spec matches", () => {
  const layout = getRuntimeLayout({ platform: "linux", hermitHome: "/tmp/hermit-home" });
  const fsImpl = {
    existsSync(target) {
      return target === layout.launcherPath || target === layout.installMetaPath;
    },
    readFileSync() {
      return JSON.stringify({ packageSpec: DEFAULT_PYPI_SPEC, wrapperVersion: "0.3.5" });
    },
  };
  assert.equal(needsBootstrap({ layout, packageSpec: DEFAULT_PYPI_SPEC, wrapperVersion: "0.3.5", fsImpl }), false);
  assert.equal(needsBootstrap({ layout, packageSpec: "cafitac-hermit-agent==other", wrapperVersion: "0.3.5", fsImpl }), true);
  assert.equal(needsBootstrap({ layout, packageSpec: DEFAULT_PYPI_SPEC, wrapperVersion: "0.3.6", fsImpl }), true);
});

test("resolvePackagedUiEntry returns the bundled hermit-ui app when present", () => {
  const fsImpl = {
    existsSync(target) {
      return String(target).endsWith("/hermit-ui/dist/app.js");
    },
  };
  const uiEntry = resolvePackagedUiEntry(fsImpl);
  assert.match(uiEntry ?? "", /hermit-ui\/dist\/app\.js$/);
});

test("shouldLaunchInteractiveUi only enables UI for no-arg tty sessions", () => {
  assert.equal(
    shouldLaunchInteractiveUi({
      args: [],
      stdoutIsTTY: true,
      stdinIsTTY: true,
      uiEntry: "/tmp/hermit-ui/dist/app.js",
    }),
    true,
  );
  assert.equal(
    shouldLaunchInteractiveUi({
      args: ["setup-codex"],
      stdoutIsTTY: true,
      stdinIsTTY: true,
      uiEntry: "/tmp/hermit-ui/dist/app.js",
    }),
    false,
  );
});

test("buildInteractiveUiEnv wires the managed python runtime into the packaged UI", () => {
  const layout = getRuntimeLayout({ platform: "linux", hermitHome: "/tmp/hermit-home" });
  const env = buildInteractiveUiEnv({
    env: { HERMIT_GATEWAY_URL: "http://127.0.0.1:8765" },
    layout,
  });
  assert.equal(env.HERMIT_PYTHON, "/tmp/hermit-home/npm-runtime/venv/bin/python");
  assert.equal(env.HERMIT_VENV_DIR, "/tmp/hermit-home/npm-runtime/venv");
  assert.match(env.HERMIT_DIR, /Project\/claude-code$/);
});

test("spawnHermit launches packaged UI for interactive no-arg sessions", async () => {
  const events = [];
  const fakeChild = {
    on() {},
  };
  const fsImpl = {
    existsSync(target) {
      const value = String(target);
      return value.endsWith("/hermit") || value.endsWith("/install-meta.json") || value.endsWith("/hermit-ui/dist/app.js");
    },
    readFileSync() {
      return JSON.stringify({ packageSpec: DEFAULT_PYPI_SPEC, wrapperVersion: "0.3.8" });
    },
  };

  await spawnHermit({
    args: [],
    env: { HERMIT_AUTO_GATEWAY: "0" },
    fsImpl,
    wrapperVersion: "0.3.8",
    stdoutIsTTY: true,
    stdinIsTTY: true,
    spawnImpl(command, args, options) {
      events.push({ command, args, options });
      return fakeChild;
    },
  });

  assert.equal(events.length, 1);
  assert.equal(events[0].command, "node");
  assert.match(events[0].args[0], /hermit-ui\/dist\/app\.js$/);
  assert.equal(events[0].options.env.HERMIT_AUTO_GATEWAY, "0");
});
