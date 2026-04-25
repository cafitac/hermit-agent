import React from 'react';
import Box from '../ink/components/Box.js';
import Text from '../ink/components/Text.js';
import type { OutputLine } from '../types.js';
import { MarkdownText } from './MarkdownText.js';

export function OutputLineView({ line }: { line: OutputLine }) {
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
