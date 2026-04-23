/**
 * Stub for Claude Code's src/utils/env.ts
 * Exports an `env` object that ink code reads for terminal detection.
 * Backed by process.env so values stay live.
 */

export interface Env {
  readonly terminal: string | undefined;
  readonly [key: string]: string | undefined;
}

export const env: Env = new Proxy(
  {},
  {
    get(_target, prop: string): string | undefined {
      if (prop === 'terminal') {
        return process.env.TERM_PROGRAM || process.env.TERM || undefined;
      }
      return process.env[prop];
    },
    has(_target, prop: string): boolean {
      if (prop === 'terminal') return true;
      return prop in process.env;
    },
  },
) as Env;
