import React, { useState } from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import useInput from '../ink/hooks/use-input.js';
import { getDialogWidth } from '../uiModel.js';
import type { ModalProps } from '../types.js';

export function ModalDialog({ title, body, actions, onAction }: ModalProps) {
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
