import React from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import type { AgentStatus } from '../types.js';
import { getDisplayVersion } from '../uiModel.js';

export function StatusBar({ status, backgrounded, toolCount }: { status: AgentStatus; backgrounded: boolean; toolCount: number }) {
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
