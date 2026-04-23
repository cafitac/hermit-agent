/**
 * Stub for Claude Code's src/utils/execFileNoThrow.ts
 * Runs a binary without throwing; returns stdout/stderr/code.
 */
import { execFile } from 'child_process';
export function execFileNoThrow(file, args = [], options = {}) {
    return new Promise((resolve) => {
        const child = execFile(file, args, {
            timeout: options.timeout ?? 5000,
            env: options.env ?? process.env,
            cwd: options.cwd,
        }, (err, stdout, stderr) => {
            const outStr = typeof stdout === 'string' ? stdout : stdout ? stdout.toString() : '';
            const errStr = typeof stderr === 'string' ? stderr : stderr ? stderr.toString() : '';
            resolve({
                stdout: outStr,
                stderr: errStr,
                code: err ? (typeof err.code === 'number' ? err.code : 1) : 0,
            });
        });
        if (options.input != null && child.stdin) {
            child.stdin.write(options.input);
            child.stdin.end();
        }
    });
}
