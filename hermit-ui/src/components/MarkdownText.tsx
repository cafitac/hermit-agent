import React, { useContext } from 'react';
import Box from '../ink/components/Box.js';
import { Ansi } from '../ink/Ansi.js';
import { TerminalSizeContext } from '../ink/components/TerminalSizeContext.js';
import { applyMarkdown } from '../markdown.js';
import { getTerminalColumns } from '../uiModel.js';
import wrapAnsi from 'wrap-ansi';

export function MarkdownText({ text }: { text: string }) {
  // 핵심 문제: yoga-layout은 긴 줄의 터미널 wrap을 모름.
  // e.g. 100자 줄이 터미널 80열에서 2줄로 wrap되어도 yoga는 1줄로 계산.
  // 결과: yoga 높이 < 실제 출력 높이 → 다음 컴포넌트가 잘못된 위치에 배치
  //       → 이전 프레임 내용이 화면에 남음(오버플로), SmartInput이 밀려남.
  //
  // 해결: wrapAnsi로 터미널 너비에 맞게 미리 wrap → 각 줄을 독립 Box로 렌더링
  //       → yoga가 실제 출력 줄 수를 정확히 알고 높이를 올바르게 계산.
  //
  // TerminalSizeContext를 사용해 AlternateScreen의 height와 동일한 소스로 컬럼 수를 읽음.
  // process.stdout.columns는 resize 직후 stale할 수 있어 height 계산 오차를 유발.
  const termSize = useContext(TerminalSizeContext);
  const columns = termSize?.columns ?? getTerminalColumns();
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
