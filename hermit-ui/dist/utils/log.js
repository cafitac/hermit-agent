/**
 * Stub for Claude Code's src/utils/log.ts
 * Only exports what src/ink/* needs: logError
 */
export function logError(err) {
    try {
        const msg = err instanceof Error ? (err.stack ?? err.message) : String(err);
        process.stderr.write(`[error] ${msg}\n`);
    }
    catch {
        // ignore
    }
}
