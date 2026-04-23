#!/usr/bin/env node
import { spawnHermit } from "../lib/runtime.js";

try {
  spawnHermit({ args: process.argv.slice(2) });
} catch (error) {
  console.error(`[hermit npm wrapper] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
