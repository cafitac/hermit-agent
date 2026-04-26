import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
/**
 * HermitAgent — React + Ink Terminal UI
 * Claude Code 스타일 대화형 터미널 인터페이스.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import render from './ink/root.js';
import Box from './ink/components/Box.js';
import Text from './ink/components/Text.js';
import { Ansi } from './ink/Ansi.js';
import { AlternateScreen } from './ink/components/AlternateScreen.js';
import InkScrollBox from './ink/components/ScrollBox.js';
import useInput from './ink/hooks/use-input.js';
import useApp from './ink/hooks/use-app.js';
import { useSelection } from './ink/hooks/use-selection.js';
import { useCopyOnSelect } from './useCopyOnSelect.js';
import { applyMarkdown } from './markdown.js';
import { getDialogWidth, getDisplayVersion, getMainInputWrapWidth, getSmartInputMode, getTerminalColumns, } from './uiModel.js';
import { getInitialStatusHints } from './startupStatus.js';
import wrapAnsi from 'wrap-ansi';
import { getHistory, addToHistory } from './history.js';
import TextInput from './TextInput.js';
import { spawn } from 'child_process';
// Module-level ref to the bridge subprocess. Exposed so the Ctrl+C handler
// (which runs in a React render context and can't easily reach into effect
// closures) can terminate the bridge before forcing process exit.
let bridgeProcRef = null;
const killBridgeAndExit = (code = 0) => {
    try {
        bridgeProcRef?.kill('SIGTERM');
    }
    catch { /* ignore */ }
    // Fallback hard-kill in case the bridge ignores SIGTERM.
    setTimeout(() => {
        try {
            bridgeProcRef?.kill('SIGKILL');
        }
        catch { /* ignore */ }
        process.exit(code);
    }, 150);
};
// ─── 마크다운 렌더러 ─────────────────────
/**
 * Markdown renderer — line-based parser producing per-line <Text>.
 *
 * applyMarkdown (marked + chalk) was attempted but produces ANSI-styled
 * strings that confuse Ink's Text wrap: consecutive responses end up with
 * the tail of one paragraph bleeding into the next "Completed in Xs" row.
 * The custom line-based parser is more predictable — each <Text> is an
 * independent flex row with its own width budget, so long paragraphs wrap
 * cleanly and blank lines stay blank.
 *
 * Paragraph spacing is achieved via explicit empty rows in the source
 * text (the model's markdown naturally has blank lines between
 * paragraphs).
 */
/**
 * Markdown renderer — Claude Code 동일 파이프라인:
 * 1. applyMarkdown(text) → marked lexer + chalk → ANSI-styled string
 * 2. <Ansi>{ansiString}</Ansi> → ANSI 파싱 → <Text color="..." bold> 계층
 *
 * <Text>{ansiString}</Text>로 직접 넣으면 ANSI escape가 width 계산을 깨뜨려
 * 이전 응답이 다음 응답 영역을 침범하는 overflow 버그가 발생한다.
 * <Ansi>가 ANSI를 파싱해서 native Ink <Text> props로 변환해야 정확함.
 */
function MarkdownText({ text }) {
    // 핵심 문제: yoga-layout은 긴 줄의 터미널 wrap을 모름.
    // e.g. 100자 줄이 터미널 80열에서 2줄로 wrap되어도 yoga는 1줄로 계산.
    // 결과: yoga 높이 < 실제 출력 높이 → 다음 컴포넌트가 잘못된 위치에 배치
    //       → 이전 프레임 내용이 화면에 남음(오버플로), SmartInput이 밀려남.
    //
    // 해결: wrapAnsi로 터미널 너비에 맞게 미리 wrap → 각 줄을 독립 Box로 렌더링
    //       → yoga가 실제 출력 줄 수를 정확히 알고 높이를 올바르게 계산.
    const columns = getTerminalColumns();
    const lines = React.useMemo(() => {
        const rendered = applyMarkdown(text);
        const wrapped = wrapAnsi(rendered, Math.max(20, columns - 6), { hard: true, wordWrap: true, trim: false });
        // 연속 빈 줄은 최대 1개로 축약 (너무 많은 빈 줄이 화면 공간 낭비)
        const result = [];
        let prevEmpty = false;
        for (const line of wrapped.split('\n')) {
            const empty = !line.trim();
            if (empty && prevEmpty)
                continue;
            result.push(line);
            prevEmpty = empty;
        }
        return result;
    }, [text, columns]);
    return (_jsx(Box, { paddingLeft: 2, flexDirection: "column", children: lines.map((line, i) => line.trim()
            ? _jsx(Box, { children: _jsx(Ansi, { children: line }) }, i)
            : _jsx(Box, { height: 1 }, i)) }));
}
// 레거시 파서 — 아래에서 MarkdownText를 대체한 이후 사용되지 않지만 참조 보존.
function _LegacyMarkdownText({ text }) {
    const lines = text.split('\n');
    const elements = [];
    let inCodeBlock = false;
    let inDiffBlock = false;
    let codeLines = [];
    let diffLines = [];
    let codeLang = '';
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        // 코드블록 시작/끝
        if (line.trimStart().startsWith('```')) {
            if (inCodeBlock) {
                // 코드블록 끝
                elements.push(_jsxs(Box, { flexDirection: "column", marginLeft: 2, marginY: 0, children: [codeLang ? _jsx(Text, { dim: true, children: `  ╭─ ${codeLang} ${'─'.repeat(Math.max(0, 40 - codeLang.length))}╮` }) : null, codeLines.map((cl, ci) => (_jsx(Text, { color: "ansi:green", children: `  │ ${cl}` }, ci))), _jsx(Text, { dim: true, children: `  ╰${'─'.repeat(43)}╯` })] }, `cb-${i}`));
                codeLines = [];
                codeLang = '';
                inCodeBlock = false;
            }
            else if (inDiffBlock) {
                // diff 블록 끝
                elements.push(_jsxs(Box, { flexDirection: "column", marginLeft: 2, marginY: 0, children: [_jsx(Text, { dim: true, children: `  ╭─ diff ${'─'.repeat(35)}╮` }), diffLines.map((dl, di) => {
                            if (dl.startsWith('@@')) {
                                return _jsx(Text, { color: "ansi:cyan", children: `  │ ${dl}` }, di);
                            }
                            else if (dl.startsWith('+')) {
                                return _jsx(Text, { color: "ansi:green", children: `  │ ${dl}` }, di);
                            }
                            else if (dl.startsWith('-')) {
                                return _jsx(Text, { color: "ansi:red", children: `  │ ${dl}` }, di);
                            }
                            return _jsx(Text, { dim: true, children: `  │ ${dl}` }, di);
                        }), _jsx(Text, { dim: true, children: `  ╰${'─'.repeat(43)}╯` })] }, `diff-${i}`));
                diffLines = [];
                inDiffBlock = false;
            }
            else {
                const lang = line.trimStart().slice(3).trim();
                if (lang === 'diff') {
                    inDiffBlock = true;
                }
                else {
                    inCodeBlock = true;
                    codeLang = lang;
                }
            }
            continue;
        }
        if (inCodeBlock) {
            codeLines.push(line);
            continue;
        }
        if (inDiffBlock) {
            diffLines.push(line);
            continue;
        }
        // 헤더
        const h3Match = line.match(/^###\s+(.+)/);
        const h2Match = line.match(/^##\s+(.+)/);
        const h1Match = line.match(/^#\s+(.+)/);
        if (h1Match) {
            elements.push(_jsx(Text, { bold: true, color: "ansi:cyan", children: `\n  ${h1Match[1]}` }, i));
            continue;
        }
        if (h2Match) {
            elements.push(_jsx(Text, { bold: true, color: "ansi:cyan", children: `\n  ${h2Match[1]}` }, i));
            continue;
        }
        if (h3Match) {
            elements.push(_jsx(Text, { bold: true, color: "ansi:white", children: `  ${h3Match[1]}` }, i));
            continue;
        }
        // 인용
        if (line.match(/^>\s/)) {
            elements.push(_jsx(Text, { dim: true, color: "ansi:yellow", children: `  ▎ ${line.slice(2)}` }, i));
            continue;
        }
        // 구분선
        if (line.match(/^-{3,}$/) || line.match(/^\*{3,}$/)) {
            elements.push(_jsx(Text, { dim: true, children: `  ${'─'.repeat(40)}` }, i));
            continue;
        }
        // 테이블 구분행 (|---|---|) → 스킵
        if (line.match(/^\|[\s-:|]+\|$/)) {
            continue;
        }
        // 테이블 행 (| col | col |)
        if (line.match(/^\|.*\|$/)) {
            const cells = line.split('|').filter(c => c.trim()).map(c => c.trim());
            // 헤더 행 판별: 다음 라인이 구분행이면 헤더
            const nextLine = i + 1 < lines.length ? lines[i + 1] : '';
            const isHeader = nextLine.match(/^\|[\s-:|]+\|$/);
            if (isHeader) {
                elements.push(_jsx(Text, { bold: true, color: "ansi:cyan", children: `  ${cells.map(c => c.padEnd(14)).join('  ')}` }, i));
            }
            else {
                elements.push(_jsx(Text, { children: `  ${cells.map(c => renderInline(c).padEnd(14)).join('  ')}` }, i));
            }
            continue;
        }
        // 리스트 (숫자)
        const olMatch = line.match(/^(\d+)\.\s\*\*(.+?)\*\*\s*(.*)/);
        if (olMatch) {
            elements.push(_jsxs(Text, { children: [_jsx(Text, { color: "ansi:cyan", children: `  ${olMatch[1]}. ` }), _jsx(Text, { bold: true, color: "ansi:white", children: olMatch[2] }), _jsx(Text, { children: olMatch[3] ? ` ${olMatch[3]}` : '' })] }, i));
            continue;
        }
        const olPlain = line.match(/^(\d+)\.\s+(.*)/);
        if (olPlain) {
            elements.push(_jsxs(Text, { children: [_jsx(Text, { color: "ansi:cyan", children: `  ${olPlain[1]}. ` }), _jsx(Text, { children: renderInline(olPlain[2]) })] }, i));
            continue;
        }
        // 리스트 (불릿)
        const ulMatch = line.match(/^[-*]\s+(.*)/);
        if (ulMatch) {
            elements.push(_jsxs(Text, { children: [_jsx(Text, { color: "ansi:cyan", children: '  • ' }), _jsx(Text, { children: renderInline(ulMatch[1]) })] }, i));
            continue;
        }
        // 들여쓰기 리스트
        const indentUl = line.match(/^(\s{2,})[-*]\s+(.*)/);
        if (indentUl) {
            const depth = Math.floor(indentUl[1].length / 2);
            elements.push(_jsxs(Text, { children: [_jsx(Text, { children: '  ' + '  '.repeat(depth) }), _jsx(Text, { dim: true, children: '◦ ' }), _jsx(Text, { children: renderInline(indentUl[2]) })] }, i));
            continue;
        }
        // 빈 줄 — Ink는 순수 빈 Text를 collapse할 수 있어 공백 1칸으로 대체
        if (line.trim() === '') {
            elements.push(_jsx(Text, { children: ' ' }, i));
            continue;
        }
        // 일반 텍스트 (인라인 마크다운 처리)
        elements.push(_jsx(Text, { children: `  ${renderInline(line)}` }, i));
    }
    return _jsx(Box, { flexDirection: "column", children: elements });
}
/** 인라인 마크다운 마커 제거 */
function renderInline(text) {
    return text
        .replace(/\*\*(.+?)\*\*/g, '$1') // **bold** → bold
        .replace(/`(.+?)`/g, '‹$1›') // `code` → ‹code›
        .replace(/\*(.+?)\*/g, '$1') // *italic* → italic
        .replace(/\*\*/g, ''); // 닫히지 않은 ** 잔여 제거
}
function ModalDialog({ title, body, actions, onAction }) {
    const [idx, setIdx] = useState(0);
    useInput((ch, key) => {
        if (key.upArrow)
            setIdx(p => Math.max(0, p - 1));
        else if (key.downArrow)
            setIdx(p => Math.min(actions.length - 1, p + 1));
        else if (key.return)
            onAction(actions[idx].key);
        else if (key.escape)
            onAction('cancel');
        // 단일 키 바로 매핑
        else {
            const match = actions.findIndex(a => a.key === ch);
            if (match >= 0)
                onAction(actions[match].key);
        }
    });
    const width = getDialogWidth();
    const border = '─'.repeat(width - 2);
    return (_jsxs(Box, { flexDirection: "column", paddingX: 1, marginY: 1, children: [_jsx(Text, { color: "ansi:yellow", bold: true, children: `  ╭─ ${title} ${'─'.repeat(Math.max(0, width - title.length - 5))}╮` }), _jsx(Text, { color: "ansi:yellow", children: `  │ ${body.substring(0, width - 4).padEnd(width - 4)} │` }), _jsx(Text, { color: "ansi:yellow", dim: true, children: `  ├${border}┤` }), actions.map((a, i) => (_jsxs(Text, { color: "ansi:yellow", children: ['  │ ', i === idx
                        ? _jsx(Text, { color: "ansi:cyan", bold: true, children: `[${a.key}] ${a.label}` })
                        : _jsx(Text, { dim: true, children: `[${a.key}] ${a.label}` }), ' '] }, a.key))), _jsx(Text, { color: "ansi:yellow", children: `  ╰${border}╯` })] }));
}
function SmartInput({ value, onChange, onSubmit, placeholder, commands }) {
    const [historyIdx, setHistoryIdx] = useState(-1);
    const [acIdx, setAcIdx] = useState(0);
    const historyRef = useRef([]);
    const columns = getTerminalColumns();
    const wrapWidth = getMainInputWrapWidth(columns);
    // 물리 커서는 숨김 (시각적 커서는 TextInput의 chalk.inverse로 표시)
    // 자동완성 후보
    const suggestions = value.startsWith('/')
        ? Object.entries(commands).filter(([cmd]) => cmd.startsWith(value)).slice(0, 8)
        : [];
    const showAc = suggestions.length > 0 && value.length > 0 && !commands[value];
    const inputMode = getSmartInputMode({ value, showAutocomplete: showAc, columns });
    useInput((input, key) => {
        // ↑ 히스토리
        if (key.upArrow) {
            const hist = historyRef.current;
            if (inputMode === 'autocomplete') {
                setAcIdx(prev => Math.max(0, prev - 1));
            }
            else if (inputMode === 'history') {
                if (hist.length === 0)
                    return;
                const next = Math.min(historyIdx + 1, hist.length - 1);
                setHistoryIdx(next);
                onChange(hist[hist.length - 1 - next]);
            }
            return;
        }
        // ↓ 히스토리
        if (key.downArrow) {
            if (inputMode === 'autocomplete') {
                setAcIdx(prev => Math.min(suggestions.length - 1, prev + 1));
            }
            else if (inputMode === 'history') {
                const next = historyIdx - 1;
                if (next < 0) {
                    setHistoryIdx(-1);
                    onChange('');
                }
                else {
                    setHistoryIdx(next);
                    onChange(historyRef.current[historyRef.current.length - 1 - next]);
                }
            }
            return;
        }
        // Tab: 자동완성 적용
        if (key.tab && showAc) {
            const selected = suggestions[acIdx];
            if (selected) {
                onChange(selected[0] + ' ');
                setAcIdx(0);
            }
            return;
        }
    });
    const handleSubmit = useCallback((val) => {
        if (showAc && suggestions[acIdx]) {
            onChange(suggestions[acIdx][0] + ' ');
            setAcIdx(0);
            return;
        }
        if (val.trim()) {
            historyRef.current.push(val.trim());
            setHistoryIdx(-1);
        }
        onSubmit(val);
    }, [showAc, suggestions, acIdx, onChange, onSubmit]);
    // 입력 변경 시 자동완성 인덱스 리셋
    const handleChange = useCallback((v) => {
        setAcIdx(0);
        setHistoryIdx(-1);
        onChange(v);
    }, [onChange]);
    return (_jsxs(Box, { flexDirection: "column", children: [showAc && (_jsxs(Box, { flexDirection: "column", paddingLeft: 3, marginBottom: 0, children: [suggestions.map(([cmd, desc], i) => (_jsx(Text, { children: i === acIdx
                            ? _jsxs(Text, { color: "ansi:cyan", bold: true, children: [`  ❯ ${cmd}`, _jsx(Text, { dim: true, children: `  ${desc}` })] })
                            : _jsx(Text, { dim: true, children: `    ${cmd}  ${desc}` }) }, cmd))), _jsx(Text, { dim: true, italic: true, children: '    Tab to complete, ↑↓ to navigate' })] })), _jsxs(Box, { children: [_jsx(Text, { color: "ansi:green", bold: true, children: '❯ ' }), _jsx(TextInput, { value: value, onChange: handleChange, onSubmit: handleSubmit, placeholder: placeholder || '', wrapWidth: wrapWidth })] })] }));
}
const PERM_LABELS = {
    yes: 'Yes',
    always: 'Yes, and always allow',
    always_allow: 'Yes, and always allow',
    no: 'No',
    no_feedback: 'No, and tell Claude why...',
};
// ─── 설정 ─────────────────────────────────
// Python executable for the backend bridge. Resolution order:
//   1. $HERMIT_PYTHON (explicit override)
//   2. $HERMIT_VENV_DIR/bin/python
//   3. $HERMIT_DIR/.venv/bin/python (if HERMIT_DIR is exported by the launcher)
//   4. fall back to plain `python3` on PATH
const PYTHON = (() => {
    if (process.env.HERMIT_PYTHON)
        return process.env.HERMIT_PYTHON;
    if (process.env.HERMIT_VENV_DIR)
        return `${process.env.HERMIT_VENV_DIR}/bin/python`;
    if (process.env.HERMIT_DIR)
        return `${process.env.HERMIT_DIR}/.venv/bin/python`;
    return 'python3';
})();
const args = process.argv.slice(2);
const getArg = (name, def) => {
    const idx = args.indexOf(name);
    return idx !== -1 && args[idx + 1] ? args[idx + 1] : def;
};
const CONFIG = {
    model: getArg('--model', ''),
    cwd: getArg('--cwd', process.cwd()),
    yolo: args.includes('--yolo'),
    baseUrl: getArg('--base-url', 'http://localhost:11434/v1'),
};
// ─── 컴포넌트: ThinkingIndicator ─────────
// Claude Code의 SPINNER_VERBS 패턴 — 랜덤 동사로 진행 중임을 표시
const SPINNER_VERBS = [
    'Accomplishing', 'Architecting', 'Baking', "Beboppin'", 'Brewing',
    'Calculating', 'Cogitating', 'Concocting', 'Contemplating', 'Cooking',
    'Crafting', 'Crunching', 'Deliberating', 'Generating', 'Hatching',
    'Hullaballooing', 'Ideating', 'Inferring', 'Manifesting', 'Musing',
    'Noodling', 'Orchestrating', 'Percolating', 'Pondering', 'Processing',
    'Reticulating', 'Ruminating', 'Scheming', 'Synthesizing', 'Thinking',
    'Tinkering', 'Transmuting', 'Wrangling', 'Zesting',
];
function ThinkingIndicator({ backgrounded, lastTool, startTime, toolCount, progressMsg }) {
    const [elapsed, setElapsed] = useState(0);
    // 세션 시작 시 랜덤 동사 선택 (리렌더 마다 바뀌지 않게 ref로 고정)
    const verbRef = useRef(SPINNER_VERBS[Math.floor(Math.random() * SPINNER_VERBS.length)]);
    useEffect(() => {
        if (!startTime)
            return;
        const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);
        return () => clearInterval(timer);
    }, [startTime]);
    if (backgrounded) {
        return _jsx(Text, { dim: true, children: '  ✻ Running in background...' });
    }
    // Claude Code 포맷: "✻ Hullaballooing… (1m 40s · 🔧3 · last: bash(...))"
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    const timeStr = m > 0 ? `${m}m ${s}s` : `${s}s`;
    const meta = [timeStr];
    if (toolCount > 0)
        meta.push(`🔧${toolCount}`);
    if (lastTool)
        meta.push(lastTool);
    const slow = elapsed > 180;
    return (_jsxs(Box, { flexDirection: "column", children: [_jsxs(Text, { color: slow ? 'ansi:yellow' : 'ansi:blue', children: [`  ✻ ${verbRef.current}… (${meta.join(' · ')})`, slow ? ' ⚠️ ESC to interrupt' : ''] }), progressMsg ? _jsx(Text, { color: "ansi:magenta", dim: true, children: '  ⎿  ' + progressMsg }) : null] }));
}
// ─── 컴포넌트: ProgressBar ───────────────
const BLOCK_CHARS = ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'];
function ProgressBar({ value, total, width = 20, label }) {
    const pct = total > 0 ? Math.min(1, value / total) : 0;
    const filled = Math.floor(pct * width);
    const remainder = pct * width - filled;
    const partialIdx = Math.floor(remainder * 8);
    const partial = filled < width ? BLOCK_CHARS[partialIdx] : '';
    const empty = Math.max(0, width - filled - (partial ? 1 : 0));
    const bar = '█'.repeat(filled) + partial + '░'.repeat(empty);
    const pctStr = `${Math.round(pct * 100)}%`;
    return (_jsxs(Box, { children: [_jsx(Text, { color: "ansi:cyan", children: '[' }), _jsx(Text, { color: "ansi:green", children: bar }), _jsx(Text, { color: "ansi:cyan", children: '] ' }), _jsx(Text, { dim: true, children: pctStr }), label ? _jsx(Text, { dim: true, children: ' ' + label }) : null] }));
}
function SessionSelectUI({ sessions, onSelect, onCancel }) {
    const [idx, setIdx] = useState(0);
    useInput((_ch, key) => {
        if (key.upArrow)
            setIdx(p => Math.max(0, p - 1));
        else if (key.downArrow)
            setIdx(p => Math.min(sessions.length - 1, p + 1));
        else if (key.return)
            onSelect(sessions[idx].session_id);
        else if (key.escape)
            onCancel();
    });
    return (_jsxs(Box, { flexDirection: "column", paddingX: 1, marginY: 1, children: [_jsx(Text, { color: "ansi:cyan", bold: true, children: '  세션 선택 (↑↓ 이동, Enter 선택, ESC 취소)' }), _jsx(Text, { children: '' }), sessions.map((s, i) => (_jsx(Box, { flexDirection: "row", children: i === idx
                    ? _jsxs(Text, { color: "ansi:cyan", bold: true, children: [`  ❯ ${s.session_id.substring(0, 8)}  `, _jsx(Text, { color: "ansi:white", children: `${s.turn_count}t` }), _jsx(Text, { dim: true, children: `  ${s.age_str}  ` }), _jsx(Text, { children: s.preview })] })
                    : _jsx(Text, { dim: true, children: `    ${s.session_id.substring(0, 8)}  ${s.turn_count}t  ${s.age_str}  ${s.preview}` }) }, s.session_id)))] }));
}
// ─── 컴포넌트: 권한 다이얼로그 ─────────────
function PermissionDialog({ ask, onSelect }) {
    const [idx, setIdx] = useState(0);
    useInput((_ch, key) => {
        if (key.upArrow)
            setIdx(p => (p === 0 ? ask.options.length - 1 : p - 1));
        else if (key.downArrow)
            setIdx(p => (p === ask.options.length - 1 ? 0 : p + 1));
        else if (key.return)
            onSelect(ask.options[idx]);
    });
    return (_jsxs(Box, { flexDirection: "column", paddingX: 1, marginY: 1, children: [_jsxs(Text, { color: "ansi:yellow", bold: true, children: ['  ⏺ Permission required: ', _jsx(Text, { color: "ansi:white", children: ask.tool })] }), _jsx(Text, { dim: true, children: '    ' + ask.summary }), _jsx(Text, { children: '' }), ask.options.map((opt, i) => (_jsxs(Text, { children: ['    ', i === idx ? _jsx(Text, { color: "ansi:cyan", bold: true, children: '❯ ' + (PERM_LABELS[opt] || opt) })
                        : _jsx(Text, { dim: true, children: '  ' + (PERM_LABELS[opt] || opt) })] }, opt)))] }));
}
// ─── 컴포넌트: 출력 행 ───────────────────
function OutputLineView({ line }) {
    switch (line.type) {
        case 'user':
            return (_jsx(Box, { paddingX: 1, marginTop: 1, flexDirection: "column", children: _jsxs(Text, { color: "ansi:green", bold: true, children: ['❯ ', _jsx(Text, { color: "ansi:white", bold: true, children: line.text })] }) }));
        case 'tool_use': {
            const detail = (line.detail || '').substring(0, 80);
            return (_jsx(Box, { paddingX: 1, children: _jsxs(Text, { children: ['  ', _jsx(Text, { color: "ansi:cyan", bold: true, children: '⏺ ' }), _jsx(Text, { color: "ansi:cyan", bold: true, children: line.name }), _jsx(Text, { dim: true, children: '(' + detail + ')' })] }) }));
        }
        case 'tool_result': {
            const text = line.text || '';
            const resultLines = text.split('\n').filter(l => l.length > 0);
            const MAX_DISPLAY = 8;
            const shown = resultLines.slice(0, MAX_DISPLAY);
            const remaining = resultLines.length - shown.length;
            const elapsedLabel = line.elapsed_s != null
                ? (line.elapsed_s < 60
                    ? `(${line.elapsed_s.toFixed(1)}s) `
                    : `(${Math.floor(line.elapsed_s / 60)}m${Math.floor(line.elapsed_s % 60)}s) `)
                : '';
            return (_jsxs(Box, { paddingX: 1, flexDirection: "column", children: [shown.map((rl, ri) => {
                        const trimmed = rl.trimStart();
                        const prefix = ri === 0 ? `    ⎿  ${elapsedLabel}` : '        ';
                        // diff 패턴 감지 (라인번호 포함: "  5+ code" 또는 순수: "+code")
                        if (/^\s*\d*\+\s/.test(rl) || (trimmed.startsWith('+') && !trimmed.startsWith('+++'))) {
                            return _jsx(Text, { color: "ansi:green", children: prefix + rl }, ri);
                        }
                        else if (/^\s*\d*-\s/.test(rl) || (trimmed.startsWith('-') && !trimmed.startsWith('---'))) {
                            return _jsx(Text, { color: "ansi:red", children: prefix + rl }, ri);
                        }
                        else if (trimmed.startsWith('@@') || trimmed.startsWith('Added') || trimmed.startsWith('Removed') || trimmed.startsWith('Changed')) {
                            return _jsx(Text, { color: "ansi:cyan", children: prefix + rl }, ri);
                        }
                        return (_jsx(Text, { dim: !line.is_error, color: line.is_error ? 'ansi:red' : undefined, children: prefix + rl.substring(0, 100) }, ri));
                    }), remaining > 0 ? (_jsx(Text, { dim: true, children: '        ... (' + remaining + ' more lines)' })) : null] }));
        }
        case 'assistant':
            return (_jsxs(Box, { paddingX: 1, marginTop: 1, flexDirection: "column", children: [_jsx(Text, { color: "ansi:blue", children: '  ⏺' }), _jsx(MarkdownText, { text: line.text || '' })] }));
        case 'system':
            return (_jsx(Box, { paddingX: 1, children: _jsx(Text, { dim: true, italic: true, children: '  ' + (line.text || '') }) }));
        case 'timer':
            return (_jsx(Box, { paddingX: 1, children: _jsxs(Text, { dim: true, children: ['  ✻ ', _jsx(Text, { dim: true, children: line.text })] }) }));
        case 'error':
            return (_jsx(Box, { paddingX: 1, children: _jsxs(Text, { color: "ansi:red", bold: true, children: ['  ✖ ', _jsx(Text, { color: "ansi:red", children: line.text })] }) }));
        default:
            return _jsx(Text, { children: line.text || '' });
    }
}
// ─── 컴포넌트: 상태 바 ───────────────────
function StatusBar({ status, backgrounded, toolCount }) {
    const ctxPct = status.ctx_pct || 0;
    const tokens = status.tokens || 0;
    const tokStr = tokens > 1000 ? Math.round(tokens / 1000) + 'k' : String(tokens);
    const displayVersion = getDisplayVersion(status.version);
    // ctx% 색상: 정상(초록) → 주의(노랑) → 위험(빨강)
    const ctxColor = ctxPct >= 80 ? 'ansi:red' : ctxPct >= 50 ? 'ansi:yellow' : 'ansi:green';
    const ctxStr = `ctx:${ctxPct}%${tokens ? '(' + tokStr + ')' : ''}`;
    // 권한 모드별 색상 + 아이콘
    // 색상 의미: 안전(초록) → 주의(노랑) → 위험(빨강)
    const permConfig = {
        plan: { icon: '📋 plan mode (read-only)', color: 'ansi:green' },
        ask: { icon: '🔒 ask permission', color: 'ansi:green' },
        allow_read: { icon: '🔓 allow read', color: 'ansi:cyan' },
        accept_edits: { icon: '🔓 accept edits', color: 'ansi:yellow' },
        yolo: { icon: '⏵⏵ bypass permissions on', color: 'ansi:red' },
        dont_ask: { icon: '⏵⏵ dont ask', color: 'ansi:red' },
    };
    const pc = permConfig[status.permission || 'allow_read'] || { icon: status.permission || '', color: 'ansi:white' };
    return (_jsxs(Box, { flexDirection: "column", paddingX: 1, children: [_jsxs(Box, { children: [_jsx(Text, { dim: true, children: '  ' }), _jsx(Text, { color: "ansi:cyan", children: `[HermitAgent#${displayVersion}]` }), _jsx(Text, { dim: true, children: ' | ' }), _jsx(Text, { color: "ansi:white", children: status.model || '?' }), _jsx(Text, { dim: true, children: ' | ' }), _jsx(Text, { dim: true, children: `session:${status.session_min || 0}m` }), _jsx(Text, { dim: true, children: ' | ' }), _jsx(Text, { color: ctxColor, children: ctxStr }), _jsx(Text, { dim: true, children: ' | ' }), _jsx(Text, { dim: true, children: `🔧${toolCount || status.turns || 0}` }), status.modified_files ? _jsxs(_Fragment, { children: [_jsx(Text, { dim: true, children: ' | ' }), _jsx(Text, { color: "ansi:yellow", children: `changes:${status.modified_files}` })] }) : null, backgrounded ? _jsxs(_Fragment, { children: [_jsx(Text, { dim: true, children: ' | ' }), _jsx(Text, { color: "ansi:magenta", children: '[BG]' })] }) : null] }), _jsx(Text, { color: pc.color, children: '  ' + pc.icon + ' (shift+tab to cycle)' })] }));
}
// ─── 컴포넌트: ScrollBox ─────────────────
const SCROLL_PAGE = 10;
function ScrollBox({ lines, streamBuf, isRunning, backgrounded, bgNotification, lastTool, taskStart, toolCount, progressMsg }) {
    const termHeight = (process.stdout.rows || 24) - 10; // 입력 영역 여유
    const pageSize = Math.max(5, termHeight);
    const [scrollOffset, setScrollOffset] = useState(0);
    // 새 출력이 올 때 자동으로 맨 아래로
    useEffect(() => {
        setScrollOffset(0);
    }, [lines.length]);
    useInput((_ch, key) => {
        if (key.pageUp || key.wheelUp) {
            setScrollOffset(prev => Math.min(prev + (key.pageUp ? SCROLL_PAGE : 3), Math.max(0, lines.length - pageSize)));
        }
        else if (key.pageDown || key.wheelDown) {
            setScrollOffset(prev => Math.max(0, prev - (key.pageDown ? SCROLL_PAGE : 3)));
        }
    });
    // scrollOffset=0이면 맨 아래, 클수록 위로 스크롤
    const visibleLines = scrollOffset === 0
        ? lines.slice(-pageSize)
        : lines.slice(Math.max(0, lines.length - pageSize - scrollOffset), lines.length - scrollOffset);
    const canScrollUp = lines.length > pageSize && scrollOffset < lines.length - pageSize;
    const canScrollDown = scrollOffset > 0;
    return (_jsxs(Box, { flexDirection: "column", children: [canScrollUp && (_jsx(Box, { paddingX: 1, children: _jsx(Text, { dim: true, children: `  ↑ more (${lines.length - pageSize - scrollOffset} lines above) · PgUp/PgDn to scroll` }) })), visibleLines.map((line, i) => (_jsx(OutputLineView, { line: line }, i))), canScrollDown && (_jsx(Box, { paddingX: 1, children: _jsx(Text, { dim: true, children: `  ↓ PgDn to scroll down` }) })), bgNotification && (_jsx(Box, { paddingX: 1, marginTop: 1, children: _jsx(Text, { color: "ansi:green", bold: true, children: `  ✔ ${bgNotification}` }) })), streamBuf && !backgrounded && scrollOffset === 0 ? (_jsxs(Box, { paddingX: 1, marginTop: 1, flexDirection: "column", children: [_jsx(Text, { color: "ansi:blue", children: '  ⏺ ' }), _jsx(MarkdownText, { text: streamBuf })] })) : null, isRunning && !streamBuf && scrollOffset === 0 ? (_jsx(Box, { paddingX: 1, children: _jsx(ThinkingIndicator, { backgrounded: backgrounded, lastTool: lastTool, startTime: taskStart, toolCount: toolCount, progressMsg: progressMsg }) })) : null] }));
}
function HistoryViewer({ lines, onClose }) {
    const pageSize = Math.max(5, (process.stdout.rows || 24) - 6);
    const [offset, setOffset] = useState(0);
    // 처음 열면 맨 아래로
    useEffect(() => {
        setOffset(0);
    }, []);
    useInput((_ch, key) => {
        if (key.pageUp)
            setOffset(prev => Math.min(prev + SCROLL_PAGE, Math.max(0, lines.length - pageSize)));
        else if (key.pageDown)
            setOffset(prev => Math.max(0, prev - SCROLL_PAGE));
        else if (key.escape)
            onClose();
        else if (key.ctrl && _ch === 'o')
            onClose();
    });
    const visibleLines = offset === 0
        ? lines.slice(-pageSize)
        : lines.slice(Math.max(0, lines.length - pageSize - offset), lines.length - offset);
    const canScrollUp = lines.length > pageSize && offset < lines.length - pageSize;
    return (_jsxs(Box, { flexDirection: "column", children: [_jsx(Box, { paddingX: 1, children: _jsx(Text, { color: "ansi:cyan", bold: true, children: '  ── 대화 히스토리 (PgUp/PgDn 스크롤 · Ctrl+O 또는 ESC 닫기) ──' }) }), canScrollUp && (_jsx(Box, { paddingX: 1, children: _jsx(Text, { dim: true, children: `  ↑ ${lines.length - pageSize - offset} lines above` }) })), visibleLines.map((line, i) => (_jsx(OutputLineView, { line: line }, i))), offset > 0 && (_jsx(Box, { paddingX: 1, children: _jsx(Text, { dim: true, children: '  ↓ PgDn for newer' }) }))] }));
}
// ─── 메인 앱 ────────────────────────────────
function HermitAgentUI() {
    const { exit } = useApp();
    const [input, setInput] = useState('');
    const columns = getTerminalColumns();
    const startupStatus = React.useMemo(() => getInitialStatusHints(), []);
    // 드래그 선택 → 자동 clipboard 복사 (Claude Code의 copy-on-select 패턴)
    // mouse tracking이 켜진 상태에서 터미널 native Cmd+C는 selection을 못 찾으므로,
    // mouse-up 시점에 OSC 52 / pbcopy로 직접 clipboard에 쓴다. 그러면 Cmd+C가
    // 이미 복사된 내용을 덮어쓰지 않아 paste가 정상 동작.
    const selection = useSelection();
    useCopyOnSelect(selection, true);
    // 커서 스타일 + 가시성 확보
    useEffect(() => {
        process.stdout.write('\x1b[?25h'); // show cursor (Ink이 숨겼을 수 있음)
        process.stdout.write('\x1b[5 q'); // blinking bar cursor
        return () => { process.stdout.write('\x1b[0 q'); }; // 기본 복원
    }, []);
    const [commands, setCommands] = useState({});
    const [lines, setLines] = useState([]);
    const [status, setStatus] = useState({
        permission: CONFIG.yolo ? 'yolo' : 'allow_read',
        model: startupStatus.model || CONFIG.model,
        version: startupStatus.version,
    });
    const [isRunning, setIsRunning] = useState(false);
    const [streamBuf, setStreamBuf] = useState('');
    const [proc, setProc] = useState(null);
    const [permissionAsk, setPermissionAsk] = useState(null);
    const [sessionList, setSessionList] = useState(null);
    const [historySearch, setHistorySearch] = useState('');
    const [historySearchMode, setHistorySearchMode] = useState(false);
    // Ctrl+B 백그라운드 모드
    const [backgrounded, setBackgrounded] = useState(false);
    const [bgNotification, setBgNotification] = useState(null);
    // Ctrl+O 히스토리 뷰어
    const [showHistory, setShowHistory] = useState(false);
    // 큰 붙여넣기 확인 모달
    const [pasteModal, setPasteModal] = useState(null);
    // Ctrl+C double-press 확인: 첫 번째 누르면 pending=true, 800ms 내 두 번째 누르면 실제 종료
    // (Claude Code의 useDoublePress + useExitOnCtrlCD 패턴)
    const [ctrlCPending, setCtrlCPending] = useState(false);
    const ctrlCTimerRef = useRef(null);
    const taskStartRef = useRef(0);
    const lastToolRef = useRef('');
    const toolCountRef = useRef(0);
    const toolUseStartRef = useRef(0);
    const mainScrollRef = useRef(null);
    const [progressMsg, setProgressMsg] = useState('');
    // 입력 히스토리 (↑/↓ 화살표) — Claude Code의 history.jsonl 패턴
    const historyItemsRef = useRef([]);
    const historyIndexRef = useRef(-1); // -1 = 현재 입력, 0+ = 히스토리 인덱스
    const savedInputRef = useRef(''); // ↑ 누르기 전 사용자 입력 보존
    const addLine = useCallback((line) => {
        setLines(prev => [...prev.slice(-500), line]);
    }, []);
    const sendToAgent = useCallback((msg) => {
        if (proc?.stdin?.writable) {
            proc.stdin.write(JSON.stringify(msg) + '\n');
        }
    }, [proc]);
    const handleMessage = useCallback((msg) => {
        switch (msg.type) {
            case 'text':
                setStreamBuf(prev => {
                    if (!prev) {
                        addLine({ type: 'assistant', text: msg.content || '' });
                    }
                    return prev;
                });
                setIsRunning(false);
                break;
            case 'streaming':
                setStreamBuf(prev => prev + (msg.token || ''));
                break;
            case 'stream_end':
                setStreamBuf(prev => {
                    if (prev)
                        addLine({ type: 'assistant', text: prev });
                    return '';
                });
                setIsRunning(false);
                break;
            case 'tool_use':
                toolCountRef.current++;
                lastToolRef.current = `${msg.name}(${(msg.detail || '').substring(0, 30)})`;
                toolUseStartRef.current = msg.ts ? msg.ts * 1000 : Date.now();
                addLine({ type: 'tool_use', name: msg.name, detail: msg.detail || '' });
                break;
            case 'progress':
                // ThinkingIndicator에 인라인 표시 (줄로 쌓지 않음, Claude Code 패턴)
                setProgressMsg(msg.content || '');
                break;
            case 'tool_result': {
                const toolEndMs = msg.ts ? msg.ts * 1000 : Date.now();
                const elapsed_s = toolUseStartRef.current ? (toolEndMs - toolUseStartRef.current) / 1000 : undefined;
                toolUseStartRef.current = 0;
                addLine({
                    type: 'tool_result',
                    text: (msg.content || '').substring(0, 2000),
                    is_error: !!msg.is_error,
                    elapsed_s,
                });
                break;
            }
            case 'status':
                setStatus(prev => ({ ...prev, ...msg }));
                break;
            case 'model_changed':
                setStatus(prev => ({ ...prev, model: msg.new_model || prev.model }));
                break;
            case 'status_field':
                setStatus(prev => ({ ...prev, [msg.field]: msg.value }));
                break;
            case 'done': {
                setIsRunning(false);
                const elapsed = taskStartRef.current ? ((Date.now() - taskStartRef.current) / 1000) : 0;
                if (elapsed > 1) {
                    const fmt = elapsed < 60 ? `${elapsed.toFixed(0)}s` : `${Math.floor(elapsed / 60)}m ${Math.floor(elapsed % 60)}s`;
                    addLine({ type: 'timer', text: `Completed in ${fmt}` });
                }
                taskStartRef.current = 0;
                lastToolRef.current = '';
                toolCountRef.current = 0;
                setProgressMsg('');
                // 백그라운드 완료 알림
                if (backgrounded) {
                    setBgNotification(`Background task completed in ${elapsed < 60 ? elapsed.toFixed(0) + 's' : Math.floor(elapsed / 60) + 'm'}`);
                    setBackgrounded(false);
                    setTimeout(() => setBgNotification(null), 5000);
                }
                // 큐에 대기 중인 입력 자동 전송
                if (inputQueueRef.current.length > 0) {
                    const queued = inputQueueRef.current.shift();
                    addLine({ type: 'user', text: queued });
                    setIsRunning(true);
                    taskStartRef.current = Date.now();
                    sendToAgent({ type: 'user_input', text: queued });
                }
                break;
            }
            case 'error':
                addLine({ type: 'error', text: msg.message || 'Unknown error' });
                setIsRunning(false);
                break;
            case 'ready':
                setStatus(prev => ({ ...prev, ...msg }));
                if (msg.commands)
                    setCommands(msg.commands);
                break;
            case 'permission_ask':
                setPermissionAsk({
                    tool: msg.tool || '',
                    summary: msg.summary || '',
                    options: msg.options || ['yes', 'always', 'no'],
                });
                break;
            case 'session_list':
                setSessionList(msg.sessions || []);
                break;
        }
    }, [addLine, backgrounded]);
    // Python 브릿지 프로세스
    useEffect(() => {
        const pyArgs = ['-m', 'hermit_agent.bridge', '--base-url', CONFIG.baseUrl, '--cwd', CONFIG.cwd];
        if (CONFIG.model)
            pyArgs.push('--model', CONFIG.model);
        if (CONFIG.yolo)
            pyArgs.push('--yolo');
        // Inherit parent env. The launcher (hermit.sh) is responsible for exporting
        // PYTHONPATH pointing to the HermitAgent source tree and the chosen venv's
        // site-packages, so this file does not hardcode any filesystem paths.
        const env = {
            ...process.env,
        };
        const child = spawn(PYTHON, pyArgs, { stdio: ['pipe', 'pipe', 'pipe'], cwd: CONFIG.cwd, env });
        bridgeProcRef = child;
        let buffer = '';
        child.stdout.on('data', (data) => {
            buffer += data.toString();
            const parts = buffer.split('\n');
            buffer = parts.pop() || '';
            for (const part of parts) {
                if (!part.trim())
                    continue;
                try {
                    handleMessage(JSON.parse(part));
                }
                catch { /* JSON이 아닌 stdout 출력은 무시 (이벤트 기반 아키텍처에서는 발생하면 안 됨) */ }
            }
        });
        child.stderr.on('data', (data) => {
            const text = data.toString().trim();
            if (text)
                addLine({ type: 'system', text: text.substring(0, 200) });
        });
        child.on('close', () => {
            addLine({ type: 'system', text: 'Agent process exited' });
            setTimeout(() => exit(), 1000);
        });
        setProc(child);
        return () => { child.kill(); };
    }, []);
    const inputQueueRef = useRef([]);
    const doSendText = useCallback((text) => {
        if (text.toLowerCase() === 'exit' || text.toLowerCase() === 'quit') {
            sendToAgent({ type: 'quit' });
            setTimeout(() => exit(), 500);
            return;
        }
        // 에이전트 실행 중이면 큐에 담기
        if (isRunning) {
            inputQueueRef.current.push(text);
            addLine({ type: 'user', text: `${text}  (queued)` });
            return;
        }
        addLine({ type: 'user', text });
        setIsRunning(true);
        taskStartRef.current = Date.now();
        sendToAgent({ type: 'user_input', text });
    }, [sendToAgent, addLine, exit, isRunning]);
    const handleSubmit = useCallback((value) => {
        const text = value.trim();
        if (!text)
            return;
        setInput('');
        // Client-only screen reset — same effect as Ctrl+L. In gateway mode the
        // backend has no persistent per-session history, so there is nothing to
        // clear server-side; intercepting here avoids the round-trip that would
        // otherwise treat "/clear" like any other slash command.
        if (text === '/clear') {
            setLines([]);
            return;
        }
        // 히스토리에 추가 + 인덱스 리셋
        addToHistory(text, CONFIG.cwd);
        historyIndexRef.current = -1;
        savedInputRef.current = '';
        historyItemsRef.current = []; // 다음 ↑ 시 reload
        // 큰 붙여넣기 감지 (1000자 이상)
        if (text.length >= 1000) {
            setPasteModal({ text });
            return;
        }
        doSendText(text);
    }, [doSendText]);
    const handlePermissionSelect = useCallback((choice) => {
        setPermissionAsk(null);
        sendToAgent({ type: 'permission_response', choice });
    }, [sendToAgent]);
    const handleSessionSelect = useCallback((sessionId) => {
        setSessionList(null);
        sendToAgent({ type: 'resume_select', session_id: sessionId });
    }, [sendToAgent]);
    const handleSessionCancel = useCallback(() => {
        setSessionList(null);
        addLine({ type: 'system', text: 'Session selection cancelled' });
    }, [addLine]);
    useInput((inp, key) => {
        // 트랙패드/휠 스크롤 (wheelUp/wheelDown) + PgUp/PgDn
        if (key.wheelUp) {
            mainScrollRef.current?.scrollBy(-3);
            return;
        }
        if (key.wheelDown) {
            mainScrollRef.current?.scrollBy(3);
            return;
        }
        if (key.pageUp) {
            mainScrollRef.current?.scrollBy(-20);
            return;
        }
        if (key.pageDown) {
            mainScrollRef.current?.scrollBy(20);
            return;
        }
        // Shift+Tab: 권한 모드 순환
        if (key.shift && key.tab) {
            const modes = ['allow_read', 'accept_edits', 'yolo'];
            const current = status.permission || 'allow_read';
            const nextIdx = (modes.indexOf(current) + 1) % modes.length;
            const nextMode = modes[nextIdx];
            setStatus(prev => ({ ...prev, permission: nextMode }));
            sendToAgent({ type: 'permission_mode', mode: nextMode });
            return;
        }
        // Ctrl+C / Ctrl+D: double-press 확인 후 종료 (Claude Code의 useExitOnCtrlCD 패턴)
        // parse-keypress가 제어 문자를 ctrl+key 또는 raw \x03/\x04 로 줄 수 있어 둘 다 감지.
        // 한글 IME 조합 중 Ctrl+C는 터미널/IME가 삼키는 경우가 있어 Ctrl+D를 대체 exit 키로 제공.
        // 첫 번째 누름: "Press X again to exit" 힌트 표시 + 800ms 타임아웃
        // 두 번째 누름 (800ms 내): 실제 bridge kill + exit
        const isCtrlC = (key.ctrl && inp === 'c') || inp === '\x03';
        const isCtrlD = (key.ctrl && inp === 'd') || inp === '\x04';
        if (isCtrlC || isCtrlD) {
            if (ctrlCPending) {
                // 두 번째 누름 → 즉시 종료
                if (ctrlCTimerRef.current) {
                    clearTimeout(ctrlCTimerRef.current);
                    ctrlCTimerRef.current = null;
                }
                cleanup();
                killBridgeAndExit(0);
                return;
            }
            // 첫 번째 누름 → pending 표시 + 800ms 타임아웃
            setCtrlCPending(true);
            if (ctrlCTimerRef.current)
                clearTimeout(ctrlCTimerRef.current);
            ctrlCTimerRef.current = setTimeout(() => {
                setCtrlCPending(false);
                ctrlCTimerRef.current = null;
            }, 800);
            return;
        }
        // Ctrl+L: 화면 클리어
        if (key.ctrl && inp === 'l') {
            setLines([]);
            return;
        }
        // Ctrl+R: 히스토리 검색 모드 토글
        if (key.ctrl && inp === 'r') {
            setHistorySearchMode(prev => !prev);
            setHistorySearch('');
            return;
        }
        // Ctrl+B: 백그라운드 전환 (에이전트 실행 중일 때만)
        if (key.ctrl && inp === 'b') {
            if (isRunning) {
                setBackgrounded(prev => {
                    const next = !prev;
                    addLine({ type: 'system', text: next ? 'Running in background... (Ctrl+B to bring back)' : 'Back in foreground' });
                    return next;
                });
            }
            return;
        }
        // Ctrl+O: 대화 히스토리 토글
        if (key.ctrl && inp === 'o') {
            setShowHistory(prev => !prev);
            return;
        }
        // ESC: 히스토리 검색 종료 또는 실행 중단
        if (key.escape) {
            if (showHistory) {
                setShowHistory(false);
                return;
            }
            if (historySearchMode) {
                setHistorySearchMode(false);
                setHistorySearch('');
                return;
            }
            if (isRunning) {
                sendToAgent({ type: 'interrupt' });
                addLine({ type: 'system', text: 'Interrupted' });
                setIsRunning(false);
                setBackgrounded(false);
            }
            return;
        }
        // ↑: 이전 히스토리
        if (key.upArrow && !isRunning) {
            if (historyItemsRef.current.length === 0) {
                historyItemsRef.current = getHistory(CONFIG.cwd);
            }
            const items = historyItemsRef.current;
            if (items.length === 0)
                return;
            const idx = historyIndexRef.current;
            if (idx === -1) {
                // 현재 입력 저장 후 첫 히스토리로
                savedInputRef.current = input;
                historyIndexRef.current = 0;
                setInput(items[0]);
            }
            else if (idx < items.length - 1) {
                historyIndexRef.current = idx + 1;
                setInput(items[idx + 1]);
            }
            return;
        }
        // ↓: 다음(최신) 히스토리 / 현재 입력 복원
        if (key.downArrow && !isRunning) {
            const idx = historyIndexRef.current;
            if (idx <= 0) {
                // 원래 입력으로 복원
                historyIndexRef.current = -1;
                setInput(savedInputRef.current);
            }
            else {
                historyIndexRef.current = idx - 1;
                setInput(historyItemsRef.current[idx - 1]);
            }
            return;
        }
    });
    // 큰 붙여넣기 모달 액션
    const handlePasteAction = useCallback((key) => {
        if (!pasteModal)
            return;
        setPasteModal(null);
        if (key === 'y') {
            doSendText(pasteModal.text);
        }
        else {
            addLine({ type: 'system', text: 'Large paste cancelled' });
        }
    }, [pasteModal, doSendText, addLine]);
    // TODO (P2): Chord 단축키 (22.8) — 구현 복잡, 추후 keybindings.json 기반으로 추가
    // TODO (P2): 키바인딩 커스터마이징 (22.9) — ~/.claude/keybindings.json 연동 예정
    // TODO (P2): 마우스 지원 (22.19) — Ink 6 제한으로 현재 불가
    // TODO (P2): Vim 모드 (22.20) — modal editing, 추후 구현
    // TODO (P2): 이미지 붙여넣기 (22.17) — 로컬 LLM 이미지 지원 확인 후 구현
    return (_jsxs(Box, { flexDirection: "column", flexGrow: 1, children: [showHistory ? (_jsx(HistoryViewer, { lines: lines, onClose: () => setShowHistory(false) })) : (_jsxs(InkScrollBox, { ref: mainScrollRef, stickyScroll: true, flexGrow: 1, flexDirection: "column", children: [_jsx(Box, { flexGrow: 1 }), lines.length === 0 && (_jsxs(Box, { flexDirection: "column", paddingX: 1, paddingY: 1, children: [_jsx(Text, { bold: true, color: "ansi:cyan", children: '  ╭─ HermitAgent v' + getDisplayVersion(status.version) + ' ─╮' }), _jsx(Text, { dim: true, children: '  │ ' + (status.model || CONFIG.model) + ' | ' + CONFIG.cwd + ' │' }), _jsx(Text, { dim: true, children: '  │ /help for commands           │' }), _jsx(Text, { bold: true, color: "ansi:cyan", children: '  ╰─────────────────────────────╯' })] })), lines.map((line, i) => _jsx(OutputLineView, { line: line }, i)), bgNotification && (_jsx(Box, { paddingX: 1, marginTop: 1, children: _jsx(Text, { color: "ansi:green", bold: true, children: `  ✔ ${bgNotification}` }) })), streamBuf && !backgrounded ? (_jsxs(Box, { paddingX: 1, marginTop: 1, flexDirection: "column", children: [_jsx(Text, { color: "ansi:blue", children: '  ⏺ ' }), _jsx(MarkdownText, { text: streamBuf })] })) : null, isRunning && !streamBuf ? (_jsx(Box, { paddingX: 1, children: _jsx(ThinkingIndicator, { backgrounded: backgrounded, lastTool: lastToolRef.current, startTime: taskStartRef.current, toolCount: toolCountRef.current, progressMsg: progressMsg }) })) : null] })), _jsxs(Box, { flexShrink: 0, flexDirection: "column", children: [_jsxs(Box, { marginTop: 1, children: [_jsx(Text, { dim: true, children: '─'.repeat(Math.max(columns - (status.session_id?.length || 0) - 4, 20)) }), _jsx(Text, { dim: true, children: ' ' + (status.session_id || '') + ' ──' })] }), pasteModal ? (_jsx(ModalDialog, { title: "Large paste detected", body: `${pasteModal.text.length} chars. Send? (↑↓ select, Enter confirm)`, actions: [
                            { key: 'y', label: 'Yes, send' },
                            { key: 'n', label: 'Cancel' },
                        ], onAction: handlePasteAction })) : sessionList ? (_jsx(SessionSelectUI, { sessions: sessionList, onSelect: handleSessionSelect, onCancel: handleSessionCancel })) : permissionAsk ? (_jsx(PermissionDialog, { ask: permissionAsk, onSelect: handlePermissionSelect })) : historySearchMode ? (_jsxs(Box, { flexDirection: "column", paddingX: 1, children: [_jsx(Text, { dim: true, italic: true, children: '  Ctrl+R: history search (ESC to cancel)' }), _jsxs(Box, { children: [_jsx(Text, { color: "ansi:yellow", bold: true, children: 'bck-i-search: ' }), _jsx(TextInput, { value: historySearch, onChange: setHistorySearch, onSubmit: (v) => {
                                            setHistorySearchMode(false);
                                            if (v.trim())
                                                setInput(v.trim());
                                            setHistorySearch('');
                                        }, wrapWidth: Math.max(10, columns - 20) })] })] })) : (_jsxs(Box, { paddingX: 1, flexDirection: "column", onPaste: (e) => setInput(prev => prev + e.data), children: [_jsx(SmartInput, { value: input, onChange: setInput, onSubmit: handleSubmit, placeholder: isRunning && !backgrounded ? 'Agent working... (ESC to interrupt, Ctrl+B to background)' : '', commands: commands }), ctrlCPending && (_jsx(Text, { dim: true, color: "ansi:yellow", children: '  Press Ctrl+C (or Ctrl+D) again to exit' }))] })), _jsx(Box, { children: _jsx(Text, { dim: true, children: '─'.repeat(columns) }) }), _jsx(StatusBar, { status: status, backgrounded: backgrounded, toolCount: toolCountRef.current })] })] }));
}
// Korean IME stdin 전처리 — DEL + 커밋 문자가 별도 청크로 올 때 합침.
// DEL(\x7f)이 단독으로 오면 잠시 대기, 다음 데이터와 합쳐서 처리.
let imePendingDel = false;
let imeTimer = null;
const IME_DEBOUNCE_MS = 30;
const origStdinEmit = process.stdin.emit.bind(process.stdin);
process.stdin.emit = function (event, ...args) {
    if (event !== 'data' || !args[0]) {
        return origStdinEmit(event, ...args);
    }
    const buf = Buffer.isBuffer(args[0]) ? args[0] : Buffer.from(args[0]);
    // Case 1: DEL + 텍스트가 같은 청크 → DEL 제거
    if (buf.includes(0x7f) && buf.length > 1) {
        const filtered = Buffer.from(buf.filter(b => b !== 0x7f));
        if (filtered.length > 0) {
            imePendingDel = false;
            if (imeTimer)
                clearTimeout(imeTimer);
            return origStdinEmit(event, filtered);
        }
    }
    // Case 2: DEL만 단독 → 잠시 대기 (IME 커밋이 바로 뒤따를 수 있음)
    if (buf.length === 1 && buf[0] === 0x7f) {
        imePendingDel = true;
        if (imeTimer)
            clearTimeout(imeTimer);
        imeTimer = setTimeout(() => {
            // 대기 시간 내 후속 데이터 없음 → 일반 backspace로 처리
            imePendingDel = false;
            origStdinEmit(event, buf);
        }, IME_DEBOUNCE_MS);
        return true;
    }
    // Case 3: 이전에 DEL이 대기 중이고 지금 텍스트가 옴 → DEL 무시, 텍스트만 전달
    if (imePendingDel) {
        imePendingDel = false;
        if (imeTimer)
            clearTimeout(imeTimer);
        return origStdinEmit(event, buf);
    }
    return origStdinEmit(event, ...args);
};
// 커서 스타일 + 비정상 종료 시 alt-screen 정리
process.stdout.write('\x1b[5 q');
const cleanup = () => {
    process.stdout.write('\x1b[0 q'); // 커서 복원
    process.stdout.write('\x1b[?1049l'); // alt-screen 종료 (안전장치)
};
process.on('exit', cleanup);
process.on('SIGINT', () => { cleanup(); process.exit(0); });
process.on('SIGTERM', () => { cleanup(); process.exit(0); });
process.on('uncaughtException', (e) => { cleanup(); console.error(e); process.exit(1); });
// exitOnCtrlC: false — Ink의 기본 Ctrl+C 핸들러가 unmount만 하고 Python bridge를
// 남겨 프로세스가 종료되지 않는 문제를 회피. 우리 useInput 핸들러가 직접 Ctrl+C를
// 감지해 bridge kill + process.exit 수행.
render(_jsx(AlternateScreen, { children: _jsx(HermitAgentUI, {}) }), { exitOnCtrlC: false });
