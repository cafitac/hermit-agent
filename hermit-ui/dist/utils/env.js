/**
 * Stub for Claude Code's src/utils/env.ts
 * Exports an `env` object that ink code reads for terminal detection.
 * Backed by process.env so values stay live.
 */
export const env = new Proxy({}, {
    get(_target, prop) {
        if (prop === 'terminal') {
            return process.env.TERM_PROGRAM || process.env.TERM || undefined;
        }
        return process.env[prop];
    },
    has(_target, prop) {
        if (prop === 'terminal')
            return true;
        return prop in process.env;
    },
});
