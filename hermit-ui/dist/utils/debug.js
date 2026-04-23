/**
 * Stub for Claude Code's src/utils/debug.ts
 * Only exports what src/ink/* needs: logForDebugging
 */
const DEBUG = process.env.HERMIT_DEBUG === '1' || process.env.DEBUG === '1';
export function logForDebugging(message, _opts) {
    if (!DEBUG)
        return;
    try {
        process.stderr.write(`[debug] ${message}\n`);
    }
    catch {
        // ignore
    }
}
