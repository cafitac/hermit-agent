#!/usr/bin/env node
import { spawnHermit, readWrapperVersion } from "../lib/runtime.js";
import { buildUpdateHintLines, checkForUpdates, runSelfUpdate } from "../lib/updates.js";

try {
  const rawArgs = process.argv.slice(2);
  const args = rawArgs.filter((arg) => arg !== "--no-update-check");
  const command = args[0] ?? "";
  const wrapperVersion = await readWrapperVersion();

  if (command === "self-update" || command === "update") {
    const result = await runSelfUpdate();
    if (!result.ok) {
      console.error(`[HERMIT] ${result.message}`);
      process.exit(1);
    }
    console.log(`[HERMIT] ${result.message}`);
    process.exit(0);
  }

  if (process.stdout.isTTY && process.stderr.isTTY && !rawArgs.includes("--no-update-check")) {
    try {
      const availability = await checkForUpdates();
      if (availability) {
        for (const line of buildUpdateHintLines(availability)) {
          console.error(line);
        }
      }
    } catch {
      // Update checks are advisory only.
    }
  }

  await spawnHermit({ args, wrapperVersion });
} catch (error) {
  console.error(`[hermit npm wrapper] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
