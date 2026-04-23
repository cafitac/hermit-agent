/**
 * Stub for Claude Code's src/bootstrap/state.ts (1758 lines in the original).
 * Only the symbols src/ink/* pulls in are exported here.
 */

export function flushInteractionTime(): void {
  // no-op — user interaction latency tracking is not needed here.
}

export function updateLastInteractionTime(): void {
  // no-op
}

export function markScrollActivity(): void {
  // no-op
}

export function getIsInteractive(): boolean {
  return !!process.stdin.isTTY && !!process.stdout.isTTY;
}
