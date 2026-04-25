import React from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';

export const BLOCK_CHARS = ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'];

export function ProgressBar({ value, total, width = 20, label }: { value: number; total: number; width?: number; label?: string }) {
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
