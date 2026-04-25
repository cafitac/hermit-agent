import React, { useState } from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import useInput from '../ink/hooks/use-input.js';
import TextInput from '../TextInput.js';
import type { PermissionAsk } from '../types.js';
import { PERM_LABELS } from '../types.js';

export function PermissionDialog({ ask, onSelect }: { ask: PermissionAsk; onSelect: (c: string) => void }) {
  const [idx, setIdx] = useState(0);
  const [customText, setCustomText] = useState('');
  const [showCustom, setShowCustom] = useState(false);

  const total = ask.options.length; // "Other" is at index `total`

  useInput((ch: string, key: { upArrow?: boolean; downArrow?: boolean; return?: boolean }) => {
    if (key.upArrow) setIdx(p => (p === 0 ? total : p - 1));
    else if (key.downArrow) setIdx(p => (p === total ? 0 : p + 1));
    else if (key.return) {
      if (idx === total) setShowCustom(true);
      else onSelect(ask.options[idx]);
    } else if (ch) {
      const d = parseInt(ch, 10);
      if (!isNaN(d) && d >= 1 && d <= total) { onSelect(ask.options[d - 1]); return; }
      const CHAR_MAP: Record<string, string> = { y: 'yes', n: 'no', a: 'always' };
      const mapped = CHAR_MAP[ch.toLowerCase()];
      if (mapped && ask.options.includes(mapped)) onSelect(mapped);
    }
  }, { isActive: !showCustom });

  return (
    <Box flexDirection="column" paddingX={1} marginY={1}>
      <Text color="ansi:yellow" bold>{'  ⏺ Permission required: '}<Text color="ansi:white">{ask.tool}</Text></Text>
      <Text dim>{'    ' + ask.summary}</Text>
      <Text>{''}</Text>
      {ask.options.map((opt, i) => (
        <Box key={i} flexDirection="row">
          <Text dim>{'    ' + (i + 1) + '. '}</Text>
          {i === idx && !showCustom
            ? <Text color="ansi:cyan" bold>{'❯ ' + (PERM_LABELS[opt] || opt)}</Text>
            : <Text dim>{'  ' + (PERM_LABELS[opt] || opt)}</Text>}
        </Box>
      ))}
      <Box flexDirection="row">
        <Text dim>{'    ' + (total + 1) + '. '}</Text>
        {idx === total && !showCustom
          ? <Text color="ansi:cyan" bold>{'❯ Other (type custom answer)'}</Text>
          : <Text dim>{'  Other (type custom answer)'}</Text>}
      </Box>
      {showCustom && (
        <Box paddingLeft={4} paddingTop={1} flexDirection="column">
          <Text dim>{'Your answer: '}</Text>
          <TextInput
            value={customText}
            onChange={setCustomText}
            onSubmit={(v) => onSelect(v.trim() || customText.trim())}
            wrapWidth={60}
          />
        </Box>
      )}
      <Text>{''}</Text>
      {showCustom
        ? <Text dim>{'    Type your answer and press Enter'}</Text>
        : <Text dim>{'    ↑↓ navigate · Enter confirm · 1-' + (total + 1) + ' shortcut · y/n/a'}</Text>}
    </Box>
  );
}
