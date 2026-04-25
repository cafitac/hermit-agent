/**
 * Runtime configuration constants for HermitAgent UI.
 */

// Python executable for the backend bridge. Resolution order:
//   1. $HERMIT_PYTHON (explicit override)
//   2. $HERMIT_VENV_DIR/bin/python
//   3. $HERMIT_DIR/.venv/bin/python (if HERMIT_DIR is exported by the launcher)
//   4. fall back to plain `python3` on PATH
export const PYTHON = (() => {
  if (process.env.HERMIT_PYTHON) return process.env.HERMIT_PYTHON;
  if (process.env.HERMIT_VENV_DIR) return `${process.env.HERMIT_VENV_DIR}/bin/python`;
  if (process.env.HERMIT_DIR) return `${process.env.HERMIT_DIR}/.venv/bin/python`;
  return 'python3';
})();

export const args = process.argv.slice(2);

export const getArg = (name: string, def: string): string => {
  const idx = args.indexOf(name);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : def;
};

export const CONFIG = {
  model: getArg('--model', ''),
  cwd: getArg('--cwd', process.cwd()),
  yolo: args.includes('--yolo'),
  baseUrl: getArg('--base-url', 'http://localhost:11434/v1'),
};

// Claude Code의 SPINNER_VERBS 패턴 — 랜덤 동사로 진행 중임을 표시
export const SPINNER_VERBS = [
  'Accomplishing', 'Architecting', 'Baking', "Beboppin'", 'Brewing',
  'Calculating', 'Cogitating', 'Concocting', 'Contemplating', 'Cooking',
  'Crafting', 'Crunching', 'Deliberating', 'Generating', 'Hatching',
  'Hullaballooing', 'Ideating', 'Inferring', 'Manifesting', 'Musing',
  'Noodling', 'Orchestrating', 'Percolating', 'Pondering', 'Processing',
  'Reticulating', 'Ruminating', 'Scheming', 'Synthesizing', 'Thinking',
  'Tinkering', 'Transmuting', 'Wrangling', 'Zesting',
];

export const SCROLL_PAGE = 10;
