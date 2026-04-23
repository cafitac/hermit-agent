/**
 * Stub for Claude Code's src/utils/intl.ts
 * Provides a cached Intl.Segmenter for grapheme clustering.
 */
let cached;
export function getGraphemeSegmenter() {
    if (!cached) {
        cached = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
    }
    return cached;
}
