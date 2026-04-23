/**
 * Stub for Claude Code's src/utils/envUtils.ts
 */
const TRUTHY = new Set(['1', 'true', 'yes', 'on']);
const FALSY = new Set(['0', 'false', 'no', 'off']);
export function isEnvTruthy(key) {
    const v = process.env[key];
    if (v === undefined)
        return false;
    return TRUTHY.has(v.toLowerCase());
}
export function isEnvDefinedFalsy(key) {
    const v = process.env[key];
    if (v === undefined)
        return false;
    return FALSY.has(v.toLowerCase());
}
export function getClaudeConfigHomeDir() {
    return (process.env.HERMIT_CONFIG_HOME ||
        `${process.env.HOME || ''}/.hermit`);
}
