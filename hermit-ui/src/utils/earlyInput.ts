/**
 * Stub for Claude Code's src/utils/earlyInput.ts
 * Claude Code captures stdin bytes that arrive before React hooks mount.
 * For the port we don't need this — ink reads stdin itself once it boots.
 */

export function stopCapturingEarlyInput(): void {
  // no-op
}

export function lastGrapheme(s: string): string | undefined {
  if (!s) return undefined;
  const chars = [...s];
  return chars[chars.length - 1];
}
