import React, { useState, useEffect, useRef } from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import { SPINNER_VERBS } from '../config.js';

export function ThinkingIndicator({ backgrounded, lastTool, startTime, toolCount, progressMsg }: {
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
