/**
 * Markdown → ANSI renderer (simplified port).
 *
 * Claude Code uses marked + cli-highlight to produce a chalk-styled string with
 * structural spacing (EOL after paragraphs, EOL+EOL after headings, EOL after
 * code blocks). That single string is then rendered in one <Text> component —
 * so paragraph spacing becomes "native" to the text flow instead of relying on
 * per-line Box margins.
 *
 * Differences from the Claude Code original:
 * - No theme system — fixed chalk palette
 * - No mailto/issue-ref linkification
 * - Synchronous cli-highlight load (fire-once on first call)
 * - Stripped down to the token types this UI actually encounters
 */
import chalk from 'chalk';
import { marked } from 'marked';
import stripAnsi from 'strip-ansi';
let highlighter = null;
// Load cli-highlight once, synchronously-ish (triggered on first applyMarkdown).
// If the load fails, we silently fall back to plain code blocks.
async function loadHighlighter() {
    if (highlighter !== null)
        return;
    try {
        const mod = await import('cli-highlight');
        highlighter = {
            highlight: mod.highlight,
            supports: mod.supportsLanguage,
        };
    }
    catch {
        highlighter = { highlight: (c) => c, supports: () => false };
    }
}
// Kick off load immediately so first render usually has it ready.
void loadHighlighter();
let markedConfigured = false;
function configureMarked() {
    if (markedConfigured)
        return;
    markedConfigured = true;
    // Disable strikethrough — models often use ~ for "approx" (e.g., ~100).
    marked.use({
        tokenizer: {
            del() {
                return undefined;
            },
        },
    });
}
const EOL = '\n';
export function applyMarkdown(content) {
    configureMarked();
    return marked
        .lexer(content)
        .map((t) => formatToken(t))
        .join('')
        .trimEnd();
}
function formatToken(token, listDepth = 0, orderedListNumber = null, parent = null) {
    switch (token.type) {
        case 'blockquote': {
            const inner = (token.tokens ?? [])
                .map((t) => formatToken(t))
                .join('');
            const bar = chalk.dim('▎');
            return inner
                .split(EOL)
                .map((line) => stripAnsi(line).trim() ? `${bar} ${chalk.italic(line)}` : line)
                .join(EOL);
        }
        case 'code': {
            const codeToken = token;
            let rendered = codeToken.text;
            if (highlighter && codeToken.lang && highlighter.supports(codeToken.lang)) {
                try {
                    rendered = highlighter.highlight(codeToken.text, { language: codeToken.lang });
                }
                catch {
                    rendered = codeToken.text;
                }
            }
            // Indent each line by 2 columns for a visible code block.
            rendered = rendered
                .split(EOL)
                .map((l) => '  ' + l)
                .join(EOL);
            return EOL + rendered + EOL + EOL;
        }
        case 'codespan': {
            // Inline `code` — cyan for visibility.
            return chalk.cyan(token.text);
        }
        case 'em':
            return chalk.italic((token.tokens ?? []).map((t) => formatToken(t, listDepth, null, parent)).join(''));
        case 'strong':
            return chalk.bold((token.tokens ?? []).map((t) => formatToken(t, listDepth, null, parent)).join(''));
        case 'heading': {
            const headingToken = token;
            const inner = (headingToken.tokens ?? [])
                .map((t) => formatToken(t))
                .join('');
            switch (headingToken.depth) {
                case 1:
                    return EOL + chalk.bold.underline.cyan(inner) + EOL + EOL;
                case 2:
                    return EOL + chalk.bold.cyan(inner) + EOL + EOL;
                default:
                    return EOL + chalk.bold(inner) + EOL + EOL;
            }
        }
        case 'hr':
            return EOL + chalk.dim('─'.repeat(40)) + EOL + EOL;
        case 'link': {
            const linkToken = token;
            const linkText = (linkToken.tokens ?? [])
                .map((t) => formatToken(t, 0, null, linkToken))
                .join('');
            return linkText || linkToken.href;
        }
        case 'list': {
            const listToken = token;
            return listToken.items
                .map((item, index) => formatToken(item, listDepth, listToken.ordered ? Number(listToken.start ?? 1) + index : null, listToken))
                .join('');
        }
        case 'list_item': {
            const indent = '  '.repeat(listDepth);
            const marker = orderedListNumber === null ? '•' : `${orderedListNumber}.`;
            const inner = (token.tokens ?? [])
                .map((t) => formatToken(t, listDepth + 1, orderedListNumber, token))
                .join('');
            // Trim trailing EOL so list items stack tightly; the list parent re-adds
            // a single EOL per item via the paragraph/text tokens.
            const trimmed = inner.replace(/\n+$/, '');
            return `${indent}${chalk.cyan(marker)} ${trimmed}${EOL}`;
        }
        case 'paragraph': {
            return ((token.tokens ?? [])
                .map((t) => formatToken(t, 0, null, token))
                .join('') + EOL);
        }
        case 'space':
            return EOL;
        case 'br':
            return EOL;
        case 'text': {
            const textToken = token;
            if (parent?.type === 'list_item' && textToken.tokens) {
                return textToken.tokens.map((t) => formatToken(t, listDepth, orderedListNumber, parent)).join('');
            }
            return textToken.text ?? '';
        }
        case 'table': {
            const tableToken = token;
            function cellText(tokens) {
                return tokens?.map((t) => formatToken(t)).join('') ?? '';
            }
            function plainText(tokens) {
                return stripAnsi(cellText(tokens));
            }
            // Compute column widths from header + all data rows
            const colWidths = tableToken.header.map((h, i) => {
                let w = plainText(h.tokens).length;
                for (const row of tableToken.rows) {
                    w = Math.max(w, plainText(row[i]?.tokens).length);
                }
                return Math.max(w, 3);
            });
            // Header row
            const headerCells = tableToken.header.map((h, i) => {
                const content = cellText(h.tokens);
                const plain = plainText(h.tokens);
                return chalk.bold(content) + ' '.repeat(Math.max(0, colWidths[i] - plain.length));
            });
            let out = '| ' + headerCells.join(' | ') + ' |' + EOL;
            // Separator row
            out += '|' + colWidths.map((w) => '-'.repeat(w + 2)).join('|') + '|' + EOL;
            // Data rows
            for (const row of tableToken.rows) {
                const cells = row.map((cell, i) => {
                    const content = cellText(cell.tokens);
                    const plain = plainText(cell.tokens);
                    return content + ' '.repeat(Math.max(0, colWidths[i] - plain.length));
                });
                out += '| ' + cells.join(' | ') + ' |' + EOL;
            }
            return out + EOL;
        }
        case 'escape':
            return token.text;
        case 'html':
        case 'def':
            return '';
        default:
            return '';
    }
}
