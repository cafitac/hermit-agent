/**
 * Stub for Claude Code's src/bootstrap/state.ts (1758 lines in the original).
 * Only the symbols src/ink/* pulls in are exported here.
 */
export function flushInteractionTime() {
    // no-op — user interaction latency tracking is not needed here.
}
export function updateLastInteractionTime() {
    // no-op
}
export function markScrollActivity() {
    // no-op
}
export function getIsInteractive() {
    return !!process.stdin.isTTY && !!process.stdout.isTTY;
}
