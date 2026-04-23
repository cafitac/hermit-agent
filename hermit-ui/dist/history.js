/**
 * Input history — append-only JSONL at ~/.hermit/history.jsonl.
 *
 * - Each entry: { display: string, timestamp: number, project: string }
 * - getHistory returns entries for the current project first, then others
 * - ↑/↓ in the prompt navigates history (most recent first)
 */
import { readFileSync, appendFileSync, mkdirSync } from 'fs';
import { join } from 'path';
const HISTORY_DIR = join(process.env.HOME || '', '.hermit');
const HISTORY_FILE = join(HISTORY_DIR, 'history.jsonl');
const MAX_HISTORY = 100;
let cachedEntries = null;
function ensureDir() {
    try {
        mkdirSync(HISTORY_DIR, { recursive: true });
    }
    catch { /* ignore */ }
}
function loadEntries() {
    if (cachedEntries)
        return cachedEntries;
    try {
        const raw = readFileSync(HISTORY_FILE, 'utf-8');
        const entries = [];
        for (const line of raw.split('\n')) {
            if (!line.trim())
                continue;
            try {
                entries.push(JSON.parse(line));
            }
            catch { /* skip malformed */ }
        }
        cachedEntries = entries;
        return entries;
    }
    catch {
        cachedEntries = [];
        return [];
    }
}
/**
 * Get history entries for navigation (most recent first).
 * Current project entries come first, then others.
 */
export function getHistory(project) {
    const entries = loadEntries();
    const projectEntries = entries.filter(e => e.project === project);
    const otherEntries = entries.filter(e => e.project !== project);
    const combined = [...projectEntries, ...otherEntries];
    // Most recent first, deduplicate by display text
    const seen = new Set();
    const result = [];
    for (let i = combined.length - 1; i >= 0; i--) {
        const text = combined[i].display.trim();
        if (!text || seen.has(text))
            continue;
        seen.add(text);
        result.push(text);
        if (result.length >= MAX_HISTORY)
            break;
    }
    return result;
}
/**
 * Add an entry to history. Appends to JSONL file.
 */
export function addToHistory(display, project) {
    if (!display.trim())
        return;
    ensureDir();
    const entry = {
        display: display.trim(),
        timestamp: Date.now(),
        project,
    };
    try {
        appendFileSync(HISTORY_FILE, JSON.stringify(entry) + '\n');
        // Invalidate cache
        cachedEntries = null;
    }
    catch { /* ignore */ }
}
