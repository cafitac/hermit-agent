import test from "node:test";
import assert from "node:assert/strict";

import {
  buildUpdateHintLines,
  compareVersions,
  formatUpdateCommand,
  shouldCheckForUpdates,
} from "../lib/updates.js";

test("compareVersions handles semver ordering", () => {
  assert.equal(compareVersions("0.3.6", "0.3.5"), 1);
  assert.equal(compareVersions("0.3.5", "0.3.5"), 0);
  assert.equal(compareVersions("0.3.4", "0.3.5"), -1);
});

test("shouldCheckForUpdates respects ttl", () => {
  const now = Date.parse("2026-04-23T15:00:00Z");
  assert.equal(shouldCheckForUpdates({}, now), true);
  assert.equal(shouldCheckForUpdates({ lastCheckedAt: "2026-04-22T10:00:00Z" }, now), true);
  assert.equal(shouldCheckForUpdates({ lastCheckedAt: "2026-04-23T14:30:00Z" }, now), false);
});

test("buildUpdateHintLines recommends self-update for published installs", () => {
  assert.deepEqual(
    buildUpdateHintLines({
      currentVersion: "0.3.5",
      latestVersion: "0.3.6",
      installContext: "published-package",
    }),
    [
      "[HERMIT] Update available: v0.3.5 -> v0.3.6",
      "[HERMIT] Run: hermit self-update",
    ],
  );
});

test("buildUpdateHintLines avoids self-update for source checkouts", () => {
  assert.deepEqual(
    buildUpdateHintLines({
      currentVersion: "0.3.5",
      latestVersion: "0.3.6",
      installContext: "source-checkout",
    }),
    [
      "[HERMIT] Update available: v0.3.5 -> v0.3.6",
      "[HERMIT] Source checkout detected. Pull latest changes and republish/reinstall locally.",
    ],
  );
});

test("formatUpdateCommand uses the published npm package name", () => {
  assert.equal(formatUpdateCommand(), "npm install -g @cafitac/hermit-agent@latest");
});
