import React, { useState, useEffect } from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import useInput from '../ink/hooks/use-input.js';
import type { ScrollBoxProps } from '../types.js';
import { SCROLL_PAGE } from '../config.js';
import { OutputLineView } from './OutputLineView.js';
import { ThinkingIndicator } from './ThinkingIndicator.js';
import { MarkdownText } from './MarkdownText.js';

export function ScrollBox({ lines, streamBuf, isRunning, backgrounded, bgNotification, lastTool, taskStart, toolCount, progressMsg }: ScrollBoxProps) {
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
