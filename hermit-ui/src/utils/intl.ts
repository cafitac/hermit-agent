/**
 * Stub for Claude Code's src/utils/intl.ts
 * Provides a cached Intl.Segmenter for grapheme clustering.
 */

let cached: Intl.Segmenter | undefined;

export function getGraphemeSegmenter(): Intl.Segmenter {
  if (!cached) {
    cached = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
  }
  return cached;
}
