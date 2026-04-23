import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_PYPI_SPEC,
  buildBootstrapPlan,
  findPythonCommand,
  getPythonCandidates,
  getRuntimeLayout,
  needsBootstrap,
} from "../lib/runtime.js";

test("runtime layout uses ~/.hermit/npm-runtime by default", () => {
  const layout = getRuntimeLayout({ platform: "darwin", hermitHome: "/tmp/hermit-home" });
  assert.equal(layout.runtimeRoot, "/tmp/hermit-home/npm-runtime");
  assert.equal(layout.venvDir, "/tmp/hermit-home/npm-runtime/venv");
  assert.equal(layout.launcherPath, "/tmp/hermit-home/npm-runtime/venv/bin/hermit");
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
      return JSON.stringify({ packageSpec: DEFAULT_PYPI_SPEC });
    },
  };
  assert.equal(needsBootstrap({ layout, packageSpec: DEFAULT_PYPI_SPEC, fsImpl }), false);
  assert.equal(needsBootstrap({ layout, packageSpec: "cafitac-hermit-agent==other", fsImpl }), true);
});
