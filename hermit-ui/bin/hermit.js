#!/usr/bin/env node
// Thin launcher — lets npm bin resolve to this file while dist/app.js
// has no shebang (it is compiled output from tsc).
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const appJs = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist', 'app.js');
const child = spawn(process.execPath, [appJs, ...process.argv.slice(2)], { stdio: 'inherit' });
child.on('exit', code => process.exit(code ?? 0));
