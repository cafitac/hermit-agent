import React, { useState, useEffect } from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import useInput from '../ink/hooks/use-input.js';
import type { HistoryViewerProps } from '../types.js';
import { SCROLL_PAGE } from '../config.js';
import { OutputLineView } from './OutputLineView.js';

export function HistoryViewer({ lines, onClose }: HistoryViewerProps) {
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
