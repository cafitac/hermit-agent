/**
 * Stub for Claude Code's src/utils/sliceAnsi.ts
 * Wraps the npm slice-ansi package (default-export style).
 */
// @ts-ignore — slice-ansi ships .d.ts but we keep loose typing for stub
import rawSliceAnsi from 'slice-ansi';
export default function sliceAnsi(string, start, end) {
    return rawSliceAnsi(string, start, end);
}
