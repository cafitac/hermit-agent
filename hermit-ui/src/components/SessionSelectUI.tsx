import React, { useState } from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import useInput from '../ink/hooks/use-input.js';
import type { SessionEntry } from '../types.js';

export function SessionSelectUI({ sessions, onSelect, onCancel }: {
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
