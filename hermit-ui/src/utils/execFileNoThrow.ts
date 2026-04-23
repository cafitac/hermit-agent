/**
 * Stub for Claude Code's src/utils/execFileNoThrow.ts
 * Runs a binary without throwing; returns stdout/stderr/code.
 */

import { execFile } from 'child_process';

export interface ExecFileResult {
  stdout: string;
  stderr: string;
  code: number;
}

export interface ExecFileOptions {
  timeout?: number;
  env?: NodeJS.ProcessEnv;
  input?: string;
  cwd?: string;
  useCwd?: boolean;
}

export function execFileNoThrow(
  file: string,
  args: readonly string[] = [],
  options: ExecFileOptions = {},
): Promise<ExecFileResult> {
  return new Promise((resolve) => {
    const child = execFile(
      file,
      args as string[],
      {
        timeout: options.timeout ?? 5000,
        env: options.env ?? process.env,
        cwd: options.cwd,
      },
      (err: any, stdout: any, stderr: any) => {
        const outStr =
          typeof stdout === 'string' ? stdout : stdout ? stdout.toString() : '';
        const errStr =
          typeof stderr === 'string' ? stderr : stderr ? stderr.toString() : '';
        resolve({
          stdout: outStr,
          stderr: errStr,
          code: err ? (typeof err.code === 'number' ? err.code : 1) : 0,
        });
      },
    );
    if (options.input != null && child.stdin) {
      child.stdin.write(options.input);
      child.stdin.end();
    }
  });
}
