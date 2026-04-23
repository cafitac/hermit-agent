/**
 * Stub for Claude Code's src/utils/semver.ts
 * Only exports gte — enough for ink's runtime version checks.
 */
function parseVersion(v) {
    const m = v.match(/^v?(\d+)\.(\d+)\.(\d+)/);
    if (!m)
        return [0, 0, 0];
    return [Number(m[1]), Number(m[2]), Number(m[3])];
}
export function gte(a, b) {
    const av = parseVersion(a);
    const bv = parseVersion(b);
    for (let i = 0; i < 3; i++) {
        const aVal = av[i] ?? 0;
        const bVal = bv[i] ?? 0;
        if (aVal > bVal)
            return true;
        if (aVal < bVal)
            return false;
    }
    return true;
}
