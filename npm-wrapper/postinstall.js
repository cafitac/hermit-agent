#!/usr/bin/env node

if (!process.stdout.isTTY) {
  process.exit(0);
}

console.log("[hermit npm wrapper] Installed.");
console.log("[hermit npm wrapper] Next:");
console.log("  hermit setup-codex");
console.log("  # or");
console.log("  hermit setup-claude");
