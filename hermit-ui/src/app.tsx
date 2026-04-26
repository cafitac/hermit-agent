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
import InkScrollBox, { type ScrollBoxHandle } from './ink/components/ScrollBox.js';
import useInput from './ink/hooks/use-input.js';
import useApp from './ink/hooks/use-app.js';
import { useSelection } from './ink/hooks/use-selection.js';
import { useCopyOnSelect } from './useCopyOnSelect.js';
import { applyMarkdown } from './markdown.js';
import {
  getDialogWidth,
  getDisplayVersion,
  getMainInputWrapWidth,
  getSmartInputMode,
  getTerminalColumns,
} from './uiModel.js';
import { getInitialStatusHints } from './startupStatus.js';
import wrapAnsi from 'wrap-ansi';
import { getHistory, addToHistory } from './history.js';
import TextInput from './TextInput.js';
import { spawn, ChildProcess } from 'child_process';

// Module-level ref to the bridge subprocess. Exposed so the Ctrl+C handler
// (which runs in a React render context and can't easily reach into effect
// closures) can terminate the bridge before forcing process exit.
let bridgeProcRef: ChildProcess | null = null;
const killBridgeAndExit = (code = 0): void => {
  try { bridgeProcRef?.kill('SIGTERM'); } catch { /* ignore */ }
  // Fallback hard-kill in case the bridge ignores SIGTERM.
  setTimeout(() => {
    try { bridgeProcRef?.kill('SIGKILL'); } catch { /* ignore */ }
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
function MarkdownText({ text }: { text: string }) {
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
    const result: string[] = [];
    let prevEmpty = false;
    for (const line of wrapped.split('\n')) {
      const empty = !line.trim();
      if (empty && prevEmpty) continue;
      result.push(line);
      prevEmpty = empty;
    }
    return result;
  }, [text, columns]);
  return (
    <Box paddingLeft={2} flexDirection="column">
      {lines.map((line, i) =>
        line.trim()
          ? <Box key={i}><Ansi>{line}</Ansi></Box>
          : <Box key={i} height={1} />
      )}
    </Box>
  );
}

// 레거시 파서 — 아래에서 MarkdownText를 대체한 이후 사용되지 않지만 참조 보존.
function _LegacyMarkdownText({ text }: { text: string }) {
  const lines = text.split('\n');
  const elements: React.ReactElement[] = [];
  let inCodeBlock = false;
  let inDiffBlock = false;
  let codeLines: string[] = [];
  let diffLines: string[] = [];
  let codeLang = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // 코드블록 시작/끝
    if (line.trimStart().startsWith('```')) {
      if (inCodeBlock) {
        // 코드블록 끝
        elements.push(
          <Box key={`cb-${i}`} flexDirection="column" marginLeft={2} marginY={0}>
            {codeLang ? <Text dim>{`  ╭─ ${codeLang} ${'─'.repeat(Math.max(0, 40 - codeLang.length))}╮`}</Text> : null}
            {codeLines.map((cl, ci) => (
              <Text key={ci} color="ansi:green">{`  │ ${cl}`}</Text>
            ))}
            <Text dim>{`  ╰${'─'.repeat(43)}╯`}</Text>
          </Box>
        );
        codeLines = [];
        codeLang = '';
        inCodeBlock = false;
      } else if (inDiffBlock) {
        // diff 블록 끝
        elements.push(
          <Box key={`diff-${i}`} flexDirection="column" marginLeft={2} marginY={0}>
            <Text dim>{`  ╭─ diff ${'─'.repeat(35)}╮`}</Text>
            {diffLines.map((dl, di) => {
              if (dl.startsWith('@@')) {
                return <Text key={di} color="ansi:cyan">{`  │ ${dl}`}</Text>;
              } else if (dl.startsWith('+')) {
                return <Text key={di} color="ansi:green">{`  │ ${dl}`}</Text>;
              } else if (dl.startsWith('-')) {
                return <Text key={di} color="ansi:red">{`  │ ${dl}`}</Text>;
              }
              return <Text key={di} dim>{`  │ ${dl}`}</Text>;
            })}
            <Text dim>{`  ╰${'─'.repeat(43)}╯`}</Text>
          </Box>
        );
        diffLines = [];
        inDiffBlock = false;
      } else {
        const lang = line.trimStart().slice(3).trim();
        if (lang === 'diff') {
          inDiffBlock = true;
        } else {
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
      elements.push(<Text key={i} bold color="ansi:cyan">{`\n  ${h1Match[1]}`}</Text>);
      continue;
    }
    if (h2Match) {
      elements.push(<Text key={i} bold color="ansi:cyan">{`\n  ${h2Match[1]}`}</Text>);
      continue;
    }
    if (h3Match) {
      elements.push(<Text key={i} bold color="ansi:white">{`  ${h3Match[1]}`}</Text>);
      continue;
    }

    // 인용
    if (line.match(/^>\s/)) {
      elements.push(<Text key={i} dim color="ansi:yellow">{`  ▎ ${line.slice(2)}`}</Text>);
      continue;
    }

    // 구분선
    if (line.match(/^-{3,}$/) || line.match(/^\*{3,}$/)) {
      elements.push(<Text key={i} dim>{`  ${'─'.repeat(40)}`}</Text>);
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
        elements.push(
          <Text key={i} bold color="ansi:cyan">{`  ${cells.map(c => c.padEnd(14)).join('  ')}`}</Text>
        );
      } else {
        elements.push(
          <Text key={i}>{`  ${cells.map(c => renderInline(c).padEnd(14)).join('  ')}`}</Text>
        );
      }
      continue;
    }

    // 리스트 (숫자)
    const olMatch = line.match(/^(\d+)\.\s\*\*(.+?)\*\*\s*(.*)/);
    if (olMatch) {
      elements.push(
        <Text key={i}>
          <Text color="ansi:cyan">{`  ${olMatch[1]}. `}</Text>
          <Text bold color="ansi:white">{olMatch[2]}</Text>
          <Text>{olMatch[3] ? ` ${olMatch[3]}` : ''}</Text>
        </Text>
      );
      continue;
    }

    const olPlain = line.match(/^(\d+)\.\s+(.*)/);
    if (olPlain) {
      elements.push(
        <Text key={i}>
          <Text color="ansi:cyan">{`  ${olPlain[1]}. `}</Text>
          <Text>{renderInline(olPlain[2])}</Text>
        </Text>
      );
      continue;
    }

    // 리스트 (불릿)
    const ulMatch = line.match(/^[-*]\s+(.*)/);
    if (ulMatch) {
      elements.push(
        <Text key={i}>
          <Text color="ansi:cyan">{'  • '}</Text>
          <Text>{renderInline(ulMatch[1])}</Text>
        </Text>
      );
      continue;
    }

    // 들여쓰기 리스트
    const indentUl = line.match(/^(\s{2,})[-*]\s+(.*)/);
    if (indentUl) {
      const depth = Math.floor(indentUl[1].length / 2);
      elements.push(
        <Text key={i}>
          <Text>{'  ' + '  '.repeat(depth)}</Text>
          <Text dim>{'◦ '}</Text>
          <Text>{renderInline(indentUl[2])}</Text>
        </Text>
      );
      continue;
    }

    // 빈 줄 — Ink는 순수 빈 Text를 collapse할 수 있어 공백 1칸으로 대체
    if (line.trim() === '') {
      elements.push(<Text key={i}>{' '}</Text>);
      continue;
    }

    // 일반 텍스트 (인라인 마크다운 처리)
    elements.push(<Text key={i}>{`  ${renderInline(line)}`}</Text>);
  }

  return <Box flexDirection="column">{elements}</Box>;
}

/** 인라인 마크다운 마커 제거 */
function renderInline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')  // **bold** → bold
    .replace(/`(.+?)`/g, '‹$1›')      // `code` → ‹code›
    .replace(/\*(.+?)\*/g, '$1')       // *italic* → italic
    .replace(/\*\*/g, '');             // 닫히지 않은 ** 잔여 제거
}

// ─── 컴포넌트: 모달 다이얼로그 ──────────────

interface ModalAction {
  key: string;
  label: string;
}

interface ModalProps {
  title: string;
  body: string;
  actions: ModalAction[];
  onAction: (key: string) => void;
}

function ModalDialog({ title, body, actions, onAction }: ModalProps) {
  const [idx, setIdx] = useState(0);

  useInput((ch: string, key: { upArrow?: boolean; downArrow?: boolean; return?: boolean; escape?: boolean }) => {
    if (key.upArrow) setIdx(p => Math.max(0, p - 1));
    else if (key.downArrow) setIdx(p => Math.min(actions.length - 1, p + 1));
    else if (key.return) onAction(actions[idx].key);
    else if (key.escape) onAction('cancel');
    // 단일 키 바로 매핑
    else {
      const match = actions.findIndex(a => a.key === ch);
      if (match >= 0) onAction(actions[match].key);
    }
  });

  const width = getDialogWidth();
  const border = '─'.repeat(width - 2);

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text color="ansi:yellow" bold>{`  ╭─ ${title} ${'─'.repeat(Math.max(0, width - title.length - 5))}╮`}</Text>
      <Text color="ansi:yellow">{`  │ ${body.substring(0, width - 4).padEnd(width - 4)} │`}</Text>
      <Text color="ansi:yellow" dim>{`  ├${border}┤`}</Text>
      {actions.map((a, i) => (
        <Text key={a.key} color="ansi:yellow">
          {'  │ '}
          {i === idx
            ? <Text color="ansi:cyan" bold>{`[${a.key}] ${a.label}`}</Text>
            : <Text dim>{`[${a.key}] ${a.label}`}</Text>}
          {' '}
        </Text>
      ))}
      <Text color="ansi:yellow">{`  ╰${border}╯`}</Text>
    </Box>
  );
}

// ─── 입력 히스토리 + 자동완성 ─────────────

interface SmartInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  placeholder?: string;
  commands: Record<string, string>;  // { "/help": "Get help..." }
}

function SmartInput({ value, onChange, onSubmit, placeholder, commands }: SmartInputProps) {
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [acIdx, setAcIdx] = useState(0);
  const historyRef = useRef<string[]>([]);
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
      } else if (inputMode === 'history') {
        if (hist.length === 0) return;
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
      } else if (inputMode === 'history') {
        const next = historyIdx - 1;
        if (next < 0) {
          setHistoryIdx(-1);
          onChange('');
        } else {
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

  const handleSubmit = useCallback((val: string) => {
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
  const handleChange = useCallback((v: string) => {
    setAcIdx(0);
    setHistoryIdx(-1);
    onChange(v);
  }, [onChange]);

  return (
    <Box flexDirection="column">
      {/* 자동완성 드롭다운 */}
      {showAc && (
        <Box flexDirection="column" paddingLeft={3} marginBottom={0}>
          {suggestions.map(([cmd, desc], i) => (
            <Text key={cmd}>
              {i === acIdx
                ? <Text color="ansi:cyan" bold>{`  ❯ ${cmd}`}<Text dim>{`  ${desc}`}</Text></Text>
                : <Text dim>{`    ${cmd}  ${desc}`}</Text>
              }
            </Text>
          ))}
          <Text dim italic>{'    Tab to complete, ↑↓ to navigate'}</Text>
        </Box>
      )}
      {/* 실제 입력 */}
      <Box>
        <Text color="ansi:green" bold>{'❯ '}</Text>
        <TextInput
          value={value}
          onChange={handleChange}
          onSubmit={handleSubmit}
          placeholder={placeholder || ''}
          wrapWidth={wrapWidth}
        />
      </Box>
    </Box>
  );
}

// ─── 타입 ────────────────────────────────

interface AgentStatus {
  version?: string;
  model?: string;
  session_id?: string;
  session_min?: number;
  ctx_pct?: number;
  tokens?: number;
  turns?: number;
  permission?: string;
  auto_agents?: number;
  modified_files?: number;
  cwd?: string;
}

interface OutputLine {
  type: 'user' | 'tool_use' | 'tool_result' | 'assistant' | 'system' | 'timer' | 'error';
  text?: string;
  name?: string;
  detail?: string;
  is_error?: boolean;
  elapsed_s?: number;
}

interface AgentMessage {
  type: string;
  content?: string;
  token?: string;
  name?: string;
  detail?: string;
  message?: string;
  is_error?: boolean;
  tool?: string;
  summary?: string;
  options?: string[];
  [key: string]: unknown;
}

interface PermissionAsk {
  tool: string;
  summary: string;
  options: string[];
}

const PERM_LABELS: Record<string, string> = {
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
  if (process.env.HERMIT_PYTHON) return process.env.HERMIT_PYTHON;
  if (process.env.HERMIT_VENV_DIR) return `${process.env.HERMIT_VENV_DIR}/bin/python`;
  if (process.env.HERMIT_DIR) return `${process.env.HERMIT_DIR}/.venv/bin/python`;
  return 'python3';
})();
const args = process.argv.slice(2);
const getArg = (name: string, def: string): string => {
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

function ThinkingIndicator({ backgrounded, lastTool, startTime, toolCount, progressMsg }: {
  backgrounded: boolean; lastTool: string; startTime: number; toolCount: number; progressMsg: string;
}) {
  const [elapsed, setElapsed] = useState(0);
  // 세션 시작 시 랜덤 동사 선택 (리렌더 마다 바뀌지 않게 ref로 고정)
  const verbRef = useRef(SPINNER_VERBS[Math.floor(Math.random() * SPINNER_VERBS.length)]);

  useEffect(() => {
    if (!startTime) return;
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [startTime]);

  if (backgrounded) {
    return <Text dim>{'  ✻ Running in background...'}</Text>;
  }

  // Claude Code 포맷: "✻ Hullaballooing… (1m 40s · 🔧3 · last: bash(...))"
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  const timeStr = m > 0 ? `${m}m ${s}s` : `${s}s`;
  const meta: string[] = [timeStr];
  if (toolCount > 0) meta.push(`🔧${toolCount}`);
  if (lastTool) meta.push(lastTool);
  const slow = elapsed > 180;

  return (
    <Box flexDirection="column">
      <Text color={slow ? 'ansi:yellow' : 'ansi:blue'}>
        {`  ✻ ${verbRef.current}… (${meta.join(' · ')})`}
        {slow ? ' ⚠️ ESC to interrupt' : ''}
      </Text>
      {progressMsg ? <Text color="ansi:magenta" dim>{'  ⎿  ' + progressMsg}</Text> : null}
    </Box>
  );
}

// ─── 컴포넌트: ProgressBar ───────────────

const BLOCK_CHARS = ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'];

function ProgressBar({ value, total, width = 20, label }: { value: number; total: number; width?: number; label?: string }) {
  const pct = total > 0 ? Math.min(1, value / total) : 0;
  const filled = Math.floor(pct * width);
  const remainder = pct * width - filled;
  const partialIdx = Math.floor(remainder * 8);
  const partial = filled < width ? BLOCK_CHARS[partialIdx] : '';
  const empty = Math.max(0, width - filled - (partial ? 1 : 0));
  const bar = '█'.repeat(filled) + partial + '░'.repeat(empty);
  const pctStr = `${Math.round(pct * 100)}%`;

  return (
    <Box>
      <Text color="ansi:cyan">{'['}</Text>
      <Text color="ansi:green">{bar}</Text>
      <Text color="ansi:cyan">{'] '}</Text>
      <Text dim>{pctStr}</Text>
      {label ? <Text dim>{' ' + label}</Text> : null}
    </Box>
  );
}

// ─── 컴포넌트: 세션 선택 UI ─────────────

interface SessionEntry {
  session_id: string;
  turn_count: number;
  age_str: string;
  preview: string;
  model: string;
}

function SessionSelectUI({ sessions, onSelect, onCancel }: {
  sessions: SessionEntry[];
  onSelect: (id: string) => void;
  onCancel: () => void;
}) {
  const [idx, setIdx] = useState(0);

  useInput((_ch: string, key: { upArrow?: boolean; downArrow?: boolean; return?: boolean; escape?: boolean }) => {
    if (key.upArrow) setIdx(p => Math.max(0, p - 1));
    else if (key.downArrow) setIdx(p => Math.min(sessions.length - 1, p + 1));
    else if (key.return) onSelect(sessions[idx].session_id);
    else if (key.escape) onCancel();
  });

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text color="ansi:cyan" bold>{'  세션 선택 (↑↓ 이동, Enter 선택, ESC 취소)'}</Text>
      <Text>{''}</Text>
      {sessions.map((s, i) => (
        <Box key={s.session_id} flexDirection="row">
          {i === idx
            ? <Text color="ansi:cyan" bold>{`  ❯ ${s.session_id.substring(0, 8)}  `}<Text color="ansi:white">{`${s.turn_count}t`}</Text><Text dim>{`  ${s.age_str}  `}</Text><Text>{s.preview}</Text></Text>
            : <Text dim>{`    ${s.session_id.substring(0, 8)}  ${s.turn_count}t  ${s.age_str}  ${s.preview}`}</Text>
          }
        </Box>
      ))}
    </Box>
  );
}

// ─── 컴포넌트: 권한 다이얼로그 ─────────────

function PermissionDialog({ ask, onSelect }: { ask: PermissionAsk; onSelect: (c: string) => void }) {
  const [idx, setIdx] = useState(0);
  useInput((_ch: string, key: { upArrow?: boolean; downArrow?: boolean; return?: boolean }) => {
    if (key.upArrow) setIdx(p => (p === 0 ? ask.options.length - 1 : p - 1));
    else if (key.downArrow) setIdx(p => (p === ask.options.length - 1 ? 0 : p + 1));
    else if (key.return) onSelect(ask.options[idx]);
  });

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text color="ansi:yellow" bold>{'  ⏺ Permission required: '}<Text color="ansi:white">{ask.tool}</Text></Text>
      <Text dim>{'    ' + ask.summary}</Text>
      <Text>{''}</Text>
      {ask.options.map((opt, i) => (
        <Text key={opt}>
          {'    '}
          {i === idx ? <Text color="ansi:cyan" bold>{'❯ ' + (PERM_LABELS[opt] || opt)}</Text>
                     : <Text dim>{'  ' + (PERM_LABELS[opt] || opt)}</Text>}
        </Text>
      ))}
    </Box>
  );
}

// ─── 컴포넌트: 출력 행 ───────────────────

function OutputLineView({ line }: { line: OutputLine }) {
  switch (line.type) {
    case 'user':
      return (
        <Box paddingX={1} marginTop={1} flexDirection="column">
          <Text color="ansi:green" bold>{'❯ '}<Text color="ansi:white" bold>{line.text}</Text></Text>
        </Box>
      );
    case 'tool_use': {
      const detail = (line.detail || '').substring(0, 80);
      return (
        <Box paddingX={1}>
          <Text>{'  '}<Text color="ansi:cyan" bold>{'⏺ '}</Text><Text color="ansi:cyan" bold>{line.name}</Text>
          <Text dim>{'(' + detail + ')'}</Text></Text>
        </Box>
      );
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

      return (
        <Box paddingX={1} flexDirection="column">
          {shown.map((rl, ri) => {
            const trimmed = rl.trimStart();
            const prefix = ri === 0 ? `    ⎿  ${elapsedLabel}` : '        ';
            // diff 패턴 감지 (라인번호 포함: "  5+ code" 또는 순수: "+code")
            if (/^\s*\d*\+\s/.test(rl) || (trimmed.startsWith('+') && !trimmed.startsWith('+++'))) {
              return <Text key={ri} color="ansi:green">{prefix + rl}</Text>;
            } else if (/^\s*\d*-\s/.test(rl) || (trimmed.startsWith('-') && !trimmed.startsWith('---'))) {
              return <Text key={ri} color="ansi:red">{prefix + rl}</Text>;
            } else if (trimmed.startsWith('@@') || trimmed.startsWith('Added') || trimmed.startsWith('Removed') || trimmed.startsWith('Changed')) {
              return <Text key={ri} color="ansi:cyan">{prefix + rl}</Text>;
            }
            return (
              <Text key={ri} dim={!line.is_error} color={line.is_error ? 'ansi:red' : undefined}>
                {prefix + rl.substring(0, 100)}
              </Text>
            );
          })}
          {remaining > 0 ? (
            <Text dim>{'        ... (' + remaining + ' more lines)'}</Text>
          ) : null}
        </Box>
      );
    }
    case 'assistant':
      return (
        <Box paddingX={1} marginTop={1} flexDirection="column">
          <Text color="ansi:blue">{'  ⏺'}</Text>
          <MarkdownText text={line.text || ''} />
        </Box>
      );
    case 'system':
      return (
        <Box paddingX={1}>
          <Text dim italic>{'  ' + (line.text || '')}</Text>
        </Box>
      );
    case 'timer':
      return (
        <Box paddingX={1}>
          <Text dim>{'  ✻ '}<Text dim>{line.text}</Text></Text>
        </Box>
      );
    case 'error':
      return (
        <Box paddingX={1}>
          <Text color="ansi:red" bold>{'  ✖ '}<Text color="ansi:red">{line.text}</Text></Text>
        </Box>
      );
    default:
      return <Text>{line.text || ''}</Text>;
  }
}

// ─── 컴포넌트: 상태 바 ───────────────────

function StatusBar({ status, backgrounded, toolCount }: { status: AgentStatus; backgrounded: boolean; toolCount: number }) {
  const ctxPct = status.ctx_pct || 0;
  const tokens = status.tokens || 0;
  const tokStr = tokens > 1000 ? Math.round(tokens / 1000) + 'k' : String(tokens);
  const displayVersion = getDisplayVersion(status.version);

  // ctx% 색상: 정상(초록) → 주의(노랑) → 위험(빨강)
  const ctxColor = ctxPct >= 80 ? 'ansi:red' : ctxPct >= 50 ? 'ansi:yellow' : 'ansi:green';
  const ctxStr = `ctx:${ctxPct}%${tokens ? '(' + tokStr + ')' : ''}`;

  // 권한 모드별 색상 + 아이콘
  // 색상 의미: 안전(초록) → 주의(노랑) → 위험(빨강)
  const permConfig: Record<string, { icon: string; color: string }> = {
    plan: { icon: '📋 plan mode (read-only)', color: 'ansi:green' },
    ask: { icon: '🔒 ask permission', color: 'ansi:green' },
    allow_read: { icon: '🔓 allow read', color: 'ansi:cyan' },
    accept_edits: { icon: '🔓 accept edits', color: 'ansi:yellow' },
    yolo: { icon: '⏵⏵ bypass permissions on', color: 'ansi:red' },
    dont_ask: { icon: '⏵⏵ dont ask', color: 'ansi:red' },
  };
  const pc = permConfig[status.permission || 'allow_read'] || { icon: status.permission || '', color: 'ansi:white' };

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box>
        <Text dim>{'  '}</Text>
        <Text color="ansi:cyan">{`[HermitAgent#${displayVersion}]`}</Text>
        <Text dim>{' | '}</Text>
        <Text color="ansi:white">{status.model || '?'}</Text>
        <Text dim>{' | '}</Text>
        <Text dim>{`session:${status.session_min || 0}m`}</Text>
        <Text dim>{' | '}</Text>
        <Text color={ctxColor}>{ctxStr}</Text>
        <Text dim>{' | '}</Text>
        <Text dim>{`🔧${toolCount || status.turns || 0}`}</Text>
        {status.modified_files ? <><Text dim>{' | '}</Text><Text color="ansi:yellow">{`changes:${status.modified_files}`}</Text></> : null}
        {backgrounded ? <><Text dim>{' | '}</Text><Text color="ansi:magenta">{'[BG]'}</Text></> : null}
      </Box>
      <Text color={pc.color}>{'  ' + pc.icon + ' (shift+tab to cycle)'}</Text>
    </Box>
  );
}

// ─── 컴포넌트: ScrollBox ─────────────────

const SCROLL_PAGE = 10;

interface ScrollBoxProps {
  lines: OutputLine[];
  streamBuf: string;
  isRunning: boolean;
  backgrounded: boolean;
  bgNotification: string | null;
  lastTool: string;
  taskStart: number;
  toolCount: number;
  progressMsg: string;
}

function ScrollBox({ lines, streamBuf, isRunning, backgrounded, bgNotification, lastTool, taskStart, toolCount, progressMsg }: ScrollBoxProps) {
  const termHeight = (process.stdout.rows || 24) - 10; // 입력 영역 여유
  const pageSize = Math.max(5, termHeight);
  const [scrollOffset, setScrollOffset] = useState(0);

  // 새 출력이 올 때 자동으로 맨 아래로
  useEffect(() => {
    setScrollOffset(0);
  }, [lines.length]);

  useInput((_ch: string, key: { pageUp?: boolean; pageDown?: boolean; wheelUp?: boolean; wheelDown?: boolean; ctrl?: boolean }) => {
    if (key.pageUp || key.wheelUp) {
      setScrollOffset(prev => Math.min(prev + (key.pageUp ? SCROLL_PAGE : 3), Math.max(0, lines.length - pageSize)));
    } else if (key.pageDown || key.wheelDown) {
      setScrollOffset(prev => Math.max(0, prev - (key.pageDown ? SCROLL_PAGE : 3)));
    }
  });

  // scrollOffset=0이면 맨 아래, 클수록 위로 스크롤
  const visibleLines = scrollOffset === 0
    ? lines.slice(-pageSize)
    : lines.slice(Math.max(0, lines.length - pageSize - scrollOffset), lines.length - scrollOffset);

  const canScrollUp = lines.length > pageSize && scrollOffset < lines.length - pageSize;
  const canScrollDown = scrollOffset > 0;

  return (
    <Box flexDirection="column">
      {/* 스크롤 위치 표시 */}
      {canScrollUp && (
        <Box paddingX={1}>
          <Text dim>{`  ↑ more (${lines.length - pageSize - scrollOffset} lines above) · PgUp/PgDn to scroll`}</Text>
        </Box>
      )}

      {visibleLines.map((line, i) => (
        <OutputLineView key={i} line={line} />
      ))}

      {canScrollDown && (
        <Box paddingX={1}>
          <Text dim>{`  ↓ PgDn to scroll down`}</Text>
        </Box>
      )}

      {/* 백그라운드 완료 알림 */}
      {bgNotification && (
        <Box paddingX={1} marginTop={1}>
          <Text color="ansi:green" bold>{`  ✔ ${bgNotification}`}</Text>
        </Box>
      )}

      {/* 스트리밍 버퍼 — 스크롤 업 중엔 숨김 (최신 내용이므로 맨 아래에서만 의미 있음) */}
      {streamBuf && !backgrounded && scrollOffset === 0 ? (
        <Box paddingX={1} marginTop={1} flexDirection="column">
          <Text color="ansi:blue">{'  ⏺ '}</Text>
          <MarkdownText text={streamBuf} />
        </Box>
      ) : null}

      {/* 실행 중 표시 — 스크롤 업 중엔 숨김 */}
      {isRunning && !streamBuf && scrollOffset === 0 ? (
        <Box paddingX={1}>
          <ThinkingIndicator backgrounded={backgrounded} lastTool={lastTool} startTime={taskStart} toolCount={toolCount} progressMsg={progressMsg} />
        </Box>
      ) : null}
    </Box>
  );
}

// ─── 컴포넌트: 대화 히스토리 뷰어 ──────────

interface HistoryViewerProps {
  lines: OutputLine[];
  onClose: () => void;
}

function HistoryViewer({ lines, onClose }: HistoryViewerProps) {
  const pageSize = Math.max(5, (process.stdout.rows || 24) - 6);
  const [offset, setOffset] = useState(0);

  // 처음 열면 맨 아래로
  useEffect(() => {
    setOffset(0);
  }, []);

  useInput((_ch: string, key: { pageUp?: boolean; pageDown?: boolean; ctrl?: boolean; escape?: boolean }) => {
    if (key.pageUp) setOffset(prev => Math.min(prev + SCROLL_PAGE, Math.max(0, lines.length - pageSize)));
    else if (key.pageDown) setOffset(prev => Math.max(0, prev - SCROLL_PAGE));
    else if (key.escape) onClose();
    else if (key.ctrl && _ch === 'o') onClose();
  });

  const visibleLines = offset === 0
    ? lines.slice(-pageSize)
    : lines.slice(Math.max(0, lines.length - pageSize - offset), lines.length - offset);

  const canScrollUp = lines.length > pageSize && offset < lines.length - pageSize;

  return (
    <Box flexDirection="column">
      <Box paddingX={1}>
        <Text color="ansi:cyan" bold>{'  ── 대화 히스토리 (PgUp/PgDn 스크롤 · Ctrl+O 또는 ESC 닫기) ──'}</Text>
      </Box>
      {canScrollUp && (
        <Box paddingX={1}>
          <Text dim>{`  ↑ ${lines.length - pageSize - offset} lines above`}</Text>
        </Box>
      )}
      {visibleLines.map((line, i) => (
        <OutputLineView key={i} line={line} />
      ))}
      {offset > 0 && (
        <Box paddingX={1}>
          <Text dim>{'  ↓ PgDn for newer'}</Text>
        </Box>
      )}
    </Box>
  );
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
  const [commands, setCommands] = useState<Record<string, string>>({});
  const [lines, setLines] = useState<OutputLine[]>([]);
  const [status, setStatus] = useState<AgentStatus>({
    permission: CONFIG.yolo ? 'yolo' : 'allow_read',
    model: startupStatus.model || CONFIG.model,
    version: startupStatus.version,
  });
  const [isRunning, setIsRunning] = useState(false);
  const [streamBuf, setStreamBuf] = useState('');
  const [proc, setProc] = useState<ChildProcess | null>(null);
  const [permissionAsk, setPermissionAsk] = useState<PermissionAsk | null>(null);
  const [sessionList, setSessionList] = useState<SessionEntry[] | null>(null);
  const [historySearch, setHistorySearch] = useState('');
  const [historySearchMode, setHistorySearchMode] = useState(false);
  // Ctrl+B 백그라운드 모드
  const [backgrounded, setBackgrounded] = useState(false);
  const [bgNotification, setBgNotification] = useState<string | null>(null);
  // Ctrl+O 히스토리 뷰어
  const [showHistory, setShowHistory] = useState(false);
  // 큰 붙여넣기 확인 모달
  const [pasteModal, setPasteModal] = useState<{ text: string } | null>(null);
  // Ctrl+C double-press 확인: 첫 번째 누르면 pending=true, 800ms 내 두 번째 누르면 실제 종료
  // (Claude Code의 useDoublePress + useExitOnCtrlCD 패턴)
  const [ctrlCPending, setCtrlCPending] = useState(false);
  const ctrlCTimerRef = useRef<NodeJS.Timeout | null>(null);
  const taskStartRef = useRef<number>(0);
  const lastToolRef = useRef<string>('');
  const toolCountRef = useRef<number>(0);
  const toolUseStartRef = useRef<number>(0);
  const mainScrollRef = useRef<ScrollBoxHandle>(null);
  const [progressMsg, setProgressMsg] = useState<string>('');
  // 입력 히스토리 (↑/↓ 화살표) — Claude Code의 history.jsonl 패턴
  const historyItemsRef = useRef<string[]>([]);
  const historyIndexRef = useRef(-1);  // -1 = 현재 입력, 0+ = 히스토리 인덱스
  const savedInputRef = useRef('');  // ↑ 누르기 전 사용자 입력 보존

  const addLine = useCallback((line: OutputLine) => {
    setLines(prev => [...prev.slice(-500), line]);
  }, []);

  const sendToAgent = useCallback((msg: object) => {
    if (proc?.stdin?.writable) {
      proc.stdin.write(JSON.stringify(msg) + '\n');
    }
  }, [proc]);

  const handleMessage = useCallback((msg: AgentMessage) => {
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
          if (prev) addLine({ type: 'assistant', text: prev });
          return '';
        });
        setIsRunning(false);
        break;
      case 'tool_use':
        toolCountRef.current++;
        lastToolRef.current = `${msg.name}(${(msg.detail || '').substring(0, 30)})`;
        toolUseStartRef.current = (msg.ts as number) ? (msg.ts as number) * 1000 : Date.now();
        addLine({ type: 'tool_use', name: msg.name, detail: msg.detail || '' });
        break;
      case 'progress':
        // ThinkingIndicator에 인라인 표시 (줄로 쌓지 않음, Claude Code 패턴)
        setProgressMsg(msg.content || '');
        break;
      case 'tool_result': {
        const toolEndMs = (msg.ts as number) ? (msg.ts as number) * 1000 : Date.now();
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
        setStatus(prev => ({ ...prev, ...(msg as unknown as AgentStatus) }));
        break;
      case 'model_changed':
        setStatus(prev => ({ ...prev, model: (msg.new_model as string) || prev.model }));
        break;
      case 'status_field':
        setStatus(prev => ({ ...prev, [(msg.field as string)]: msg.value }));
        break;
      case 'done': {
        setIsRunning(false);
        const elapsed = taskStartRef.current ? ((Date.now() - taskStartRef.current) / 1000) : 0;
        if (elapsed > 1) {
          const fmt = elapsed < 60 ? `${elapsed.toFixed(0)}s` : `${Math.floor(elapsed/60)}m ${Math.floor(elapsed%60)}s`;
          addLine({ type: 'timer', text: `Completed in ${fmt}` });
        }
        taskStartRef.current = 0;
        lastToolRef.current = '';
        toolCountRef.current = 0;
        setProgressMsg('');

        // 백그라운드 완료 알림
        if (backgrounded) {
          setBgNotification(`Background task completed in ${elapsed < 60 ? elapsed.toFixed(0) + 's' : Math.floor(elapsed/60) + 'm'}`);
          setBackgrounded(false);
          setTimeout(() => setBgNotification(null), 5000);
        }

        // 큐에 대기 중인 입력 자동 전송
        if (inputQueueRef.current.length > 0) {
          const queued = inputQueueRef.current.shift()!;
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
        setStatus(prev => ({ ...prev, ...(msg as unknown as AgentStatus) }));
        if (msg.commands) setCommands(msg.commands as Record<string, string>);
        break;
      case 'permission_ask':
        setPermissionAsk({
          tool: msg.tool || '',
          summary: msg.summary || '',
          options: (msg.options as string[]) || ['yes', 'always', 'no'],
        });
        break;
      case 'session_list':
        setSessionList((msg.sessions as SessionEntry[]) || []);
        break;
    }
  }, [addLine, backgrounded]);

  // Python 브릿지 프로세스
  useEffect(() => {
    const pyArgs = ['-m', 'hermit_agent.bridge', '--base-url', CONFIG.baseUrl, '--cwd', CONFIG.cwd];
    if (CONFIG.model) pyArgs.push('--model', CONFIG.model);
    if (CONFIG.yolo) pyArgs.push('--yolo');

    // Inherit parent env. PYTHONPATH and venv paths are set by the hermit
    // launcher (hermit-ui/bin/hermit.js) before spawning this process.
    const env: Record<string, string> = {
      ...process.env as Record<string, string>,
    };

    const child = spawn(PYTHON, pyArgs, { stdio: ['pipe', 'pipe', 'pipe'], cwd: CONFIG.cwd, env });
    bridgeProcRef = child;
    let buffer = '';

    child.stdout!.on('data', (data: Buffer) => {
      buffer += data.toString();
      const parts = buffer.split('\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        if (!part.trim()) continue;
        try { handleMessage(JSON.parse(part)); }
        catch { /* JSON이 아닌 stdout 출력은 무시 (이벤트 기반 아키텍처에서는 발생하면 안 됨) */ }
      }
    });

    child.stderr!.on('data', (data: Buffer) => {
      const text = data.toString().trim();
      if (text) addLine({ type: 'system', text: text.substring(0, 200) });
    });

    child.on('close', () => {
      addLine({ type: 'system', text: 'Agent process exited' });
      setTimeout(() => exit(), 1000);
    });

    setProc(child);
    return () => { child.kill(); };
  }, []);

  const inputQueueRef = useRef<string[]>([]);

  const doSendText = useCallback((text: string) => {
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

  const handleSubmit = useCallback((value: string) => {
    const text = value.trim();
    if (!text) return;
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
    historyItemsRef.current = [];  // 다음 ↑ 시 reload

    // 큰 붙여넣기 감지 (1000자 이상)
    if (text.length >= 1000) {
      setPasteModal({ text });
      return;
    }

    doSendText(text);
  }, [doSendText]);

  const handlePermissionSelect = useCallback((choice: string) => {
    setPermissionAsk(null);
    sendToAgent({ type: 'permission_response', choice });
  }, [sendToAgent]);

  const handleSessionSelect = useCallback((sessionId: string) => {
    setSessionList(null);
    sendToAgent({ type: 'resume_select', session_id: sessionId });
  }, [sendToAgent]);

  const handleSessionCancel = useCallback(() => {
    setSessionList(null);
    addLine({ type: 'system', text: 'Session selection cancelled' });
  }, [addLine]);

  useInput((inp: string, key: any) => {
    // 트랙패드/휠 스크롤 (wheelUp/wheelDown) + PgUp/PgDn
    if (key.wheelUp) { mainScrollRef.current?.scrollBy(-3); return; }
    if (key.wheelDown) { mainScrollRef.current?.scrollBy(3); return; }
    if (key.pageUp) { mainScrollRef.current?.scrollBy(-20); return; }
    if (key.pageDown) { mainScrollRef.current?.scrollBy(20); return; }

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
      if (ctrlCTimerRef.current) clearTimeout(ctrlCTimerRef.current);
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
      if (items.length === 0) return;
      const idx = historyIndexRef.current;
      if (idx === -1) {
        // 현재 입력 저장 후 첫 히스토리로
        savedInputRef.current = input;
        historyIndexRef.current = 0;
        setInput(items[0]);
      } else if (idx < items.length - 1) {
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
      } else {
        historyIndexRef.current = idx - 1;
        setInput(historyItemsRef.current[idx - 1]);
      }
      return;
    }
  });

  // 큰 붙여넣기 모달 액션
  const handlePasteAction = useCallback((key: string) => {
    if (!pasteModal) return;
    setPasteModal(null);
    if (key === 'y') {
      doSendText(pasteModal.text);
    } else {
      addLine({ type: 'system', text: 'Large paste cancelled' });
    }
  }, [pasteModal, doSendText, addLine]);

  // TODO (P2): Chord 단축키 (22.8) — 구현 복잡, 추후 keybindings.json 기반으로 추가
  // TODO (P2): 키바인딩 커스터마이징 (22.9) — ~/.claude/keybindings.json 연동 예정
  // TODO (P2): 마우스 지원 (22.19) — Ink 6 제한으로 현재 불가
  // TODO (P2): Vim 모드 (22.20) — modal editing, 추후 구현
  // TODO (P2): 이미지 붙여넣기 (22.17) — 로컬 LLM 이미지 지원 확인 후 구현

  return (
    <Box flexDirection="column" flexGrow={1}>
      {/* Ink ScrollBox — overflow:scroll, stickyScroll, 트랙패드/휠/PgUp/PgDn 지원 */}
      {showHistory ? (
        <HistoryViewer lines={lines} onClose={() => setShowHistory(false)} />
      ) : (
        <InkScrollBox ref={mainScrollRef} stickyScroll flexGrow={1} flexDirection="column">
          {/* Claude Code 패턴: flexGrow 스페이서가 컨텐츠를 아래로 밀어 bottom-up 효과 */}
          <Box flexGrow={1} />

          {/* 시작 헤더 (대화 없을 때만) */}
          {lines.length === 0 && (
            <Box flexDirection="column" paddingX={1} paddingY={1}>
              <Text bold color="ansi:cyan">{'  ╭─ HermitAgent v' + getDisplayVersion(status.version) + ' ─╮'}</Text>
              <Text dim>{'  │ ' + (status.model || CONFIG.model) + ' | ' + CONFIG.cwd + ' │'}</Text>
              <Text dim>{'  │ /help for commands           │'}</Text>
              <Text bold color="ansi:cyan">{'  ╰─────────────────────────────╯'}</Text>
            </Box>
          )}

          {/* 모든 대화 라인 (슬라이싱 없음 — ScrollBox가 뷰포트 culling 처리) */}
          {lines.map((line, i) => <OutputLineView key={i} line={line} />)}

          {/* 백그라운드 완료 알림 */}
          {bgNotification && (
            <Box paddingX={1} marginTop={1}>
              <Text color="ansi:green" bold>{`  ✔ ${bgNotification}`}</Text>
            </Box>
          )}

          {/* 스트리밍 버퍼 */}
          {streamBuf && !backgrounded ? (
            <Box paddingX={1} marginTop={1} flexDirection="column">
              <Text color="ansi:blue">{'  ⏺ '}</Text>
              <MarkdownText text={streamBuf} />
            </Box>
          ) : null}

          {/* 실행 중 표시 */}
          {isRunning && !streamBuf ? (
            <Box paddingX={1}>
              <ThinkingIndicator backgrounded={backgrounded} lastTool={lastToolRef.current} startTime={taskStartRef.current} toolCount={toolCountRef.current} progressMsg={progressMsg} />
            </Box>
          ) : null}
        </InkScrollBox>
      )}

      {/* 입력 영역 — flexShrink={0}으로 항상 하단 고정 */}
      <Box flexShrink={0} flexDirection="column">

      {/* 구분선 + 세션명 */}
      <Box marginTop={1}>
        <Text dim>{'─'.repeat(Math.max(columns - (status.session_id?.length || 0) - 4, 20))}</Text>
        <Text dim>{' ' + (status.session_id || '') + ' ──'}</Text>
      </Box>

      {/* 큰 붙여넣기 확인 모달 */}
      {pasteModal ? (
        <ModalDialog
          title="Large paste detected"
          body={`${pasteModal.text.length} chars. Send? (↑↓ select, Enter confirm)`}
          actions={[
            { key: 'y', label: 'Yes, send' },
            { key: 'n', label: 'Cancel' },
          ]}
          onAction={handlePasteAction}
        />
      ) : sessionList ? (
        <SessionSelectUI
          sessions={sessionList}
          onSelect={handleSessionSelect}
          onCancel={handleSessionCancel}
        />
      ) : permissionAsk ? (
        <PermissionDialog ask={permissionAsk} onSelect={handlePermissionSelect} />
      ) : historySearchMode ? (
        <Box flexDirection="column" paddingX={1}>
          <Text dim italic>{'  Ctrl+R: history search (ESC to cancel)'}</Text>
          <Box>
            <Text color="ansi:yellow" bold>{'bck-i-search: '}</Text>
            <TextInput
              value={historySearch}
              onChange={setHistorySearch}
              onSubmit={(v) => {
                setHistorySearchMode(false);
                if (v.trim()) setInput(v.trim());
                setHistorySearch('');
              }}
              wrapWidth={Math.max(10, columns - 20)}
            />
          </Box>
        </Box>
      ) : (
        <Box paddingX={1} flexDirection="column" onPaste={(e: any) => setInput(prev => prev + e.data)}>
          <SmartInput
            value={input}
            onChange={setInput}
            onSubmit={handleSubmit}
            placeholder={isRunning && !backgrounded ? 'Agent working... (ESC to interrupt, Ctrl+B to background)' : ''}
            commands={commands}
          />
          {ctrlCPending && (
            <Text dim color="ansi:yellow">{'  Press Ctrl+C (or Ctrl+D) again to exit'}</Text>
          )}
        </Box>
      )}

      {/* 하단 구분선 */}
      <Box>
        <Text dim>{'─'.repeat(columns)}</Text>
      </Box>

      {/* 상태 바 */}
      <StatusBar status={status} backgrounded={backgrounded} toolCount={toolCountRef.current} />
      </Box>{/* end flexShrink={0} 입력 영역 */}
    </Box>
  );
}

// Korean IME stdin 전처리 — DEL + 커밋 문자가 별도 청크로 올 때 합침.
// DEL(\x7f)이 단독으로 오면 잠시 대기, 다음 데이터와 합쳐서 처리.
let imePendingDel = false;
let imeTimer: ReturnType<typeof setTimeout> | null = null;
const IME_DEBOUNCE_MS = 30;

const origStdinEmit = process.stdin.emit.bind(process.stdin);
(process.stdin as any).emit = function(event: string, ...args: any[]) {
  if (event !== 'data' || !args[0]) {
    return origStdinEmit(event, ...args);
  }

  const buf = Buffer.isBuffer(args[0]) ? args[0] : Buffer.from(args[0]);

  // Case 1: DEL + 텍스트가 같은 청크 → DEL 제거
  if (buf.includes(0x7f) && buf.length > 1) {
    const filtered = Buffer.from(buf.filter(b => b !== 0x7f));
    if (filtered.length > 0) {
      imePendingDel = false;
      if (imeTimer) clearTimeout(imeTimer);
      return origStdinEmit(event, filtered);
    }
  }

  // Case 2: DEL만 단독 → 잠시 대기 (IME 커밋이 바로 뒤따를 수 있음)
  if (buf.length === 1 && buf[0] === 0x7f) {
    imePendingDel = true;
    if (imeTimer) clearTimeout(imeTimer);
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
    if (imeTimer) clearTimeout(imeTimer);
    return origStdinEmit(event, buf);
  }

  return origStdinEmit(event, ...args);
};

// 커서 스타일 + 비정상 종료 시 alt-screen 정리
process.stdout.write('\x1b[5 q');
const cleanup = () => {
  process.stdout.write('\x1b[0 q');     // 커서 복원
  process.stdout.write('\x1b[?1049l');  // alt-screen 종료 (안전장치)
};
process.on('exit', cleanup);
process.on('SIGINT', () => { cleanup(); process.exit(0); });
process.on('SIGTERM', () => { cleanup(); process.exit(0); });
process.on('uncaughtException', (e) => { cleanup(); console.error(e); process.exit(1); });

// exitOnCtrlC: false — Ink의 기본 Ctrl+C 핸들러가 unmount만 하고 Python bridge를
// 남겨 프로세스가 종료되지 않는 문제를 회피. 우리 useInput 핸들러가 직접 Ctrl+C를
// 감지해 bridge kill + process.exit 수행.
render(<AlternateScreen><HermitAgentUI /></AlternateScreen>, { exitOnCtrlC: false });
