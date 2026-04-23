# Claude Code Ink 이식 작업 참조 문서

## 작업 원칙 (매 작업 시작 전 상기)

1. **Claude Code와 동일한 방식으로 구현한다.** 추측하지 말고 원본 파일을 먼저 Read.
2. **원본 파일 경로**: `/Users/reddit/Project/claude-code/src/ink/*`, `/Users/reddit/Project/claude-code/src/native-ts/yoga-layout/*`
3. **차이나면 반드시 원본 확인.** 버그 추적 시 diff로 원본과 비교.
4. **Stub으로 대체한 곳은 명확히 표시한다.** 기능 유지가 핵심, 내부 구현은 최소화.
5. **React Compiler 출력 형태 그대로 복사.** `const $ = _c(N)` 같은 코드는 수정 금지 — 이미 컴파일된 중간 파일임.

## 디렉토리 매핑

| 원본 (claude-code) | 이식 (cafibot-ui) | 전략 |
|---|---|---|
| `src/ink/*` | `src/ink/*` | 전체 복사 (48 파일, 1.2MB) |
| `src/native-ts/yoga-layout/*` | `src/native-ts/yoga-layout/*` | 전체 복사 (2712줄, pure TS port) |
| `src/bootstrap/state.ts` (1758줄) | `src/bootstrap/state.ts` (stub) | 필요 함수만 stub |
| `src/utils/*` (각 ~200줄) | `src/utils/*` (stub) | 필요 함수만 stub |

## 필요한 외부 함수 (stub 대상)

### `src/bootstrap/state.ts`
- `flushInteractionTime()` — no-op
- `markScrollActivity()` — no-op
- `updateLastInteractionTime()` — no-op
- `getIsInteractive()` — `true` 반환 (TTY 체크)

### `src/utils/debug.ts`
- `logForDebugging(msg, opts?)` — stderr 또는 no-op

### `src/utils/log.ts`
- `logError(err)` — stderr

### `src/utils/env.ts`
- `env` object — `{ platform, terminal, isCI, ... }` stub

### `src/utils/envUtils.ts`
- `isEnvTruthy(key)` — `['1','true','yes'].includes((process.env[key]||'').toLowerCase())`
- `isEnvDefinedFalsy(key)` — 반대

### `src/utils/execFileNoThrow.ts`
- `execFileNoThrow(cmd, args, ...)` — `child_process.execFile` wrapper

### `src/utils/earlyInput.ts`
- `stopCapturingEarlyInput()` — no-op
- `lastGrapheme(s)` — `[...s].at(-1)`

### `src/utils/fullscreen.ts`
- `isMouseClicksDisabled()` — `false`

### `src/utils/intl.ts`
- `getGraphemeSegmenter()` — `new Intl.Segmenter(undefined, { granularity: 'grapheme' })`

### `src/utils/semver.ts`
- `gte(a, b)` — 1줄 semver 비교

### `src/utils/sliceAnsi.ts`
- `sliceAnsi(s, start, end)` — npm `slice-ansi` 패키지 사용 또는 단순 구현

## npm 의존성 추가

```json
"dependencies": {
  "auto-bind": "^5",
  "lodash-es": "^4",
  "react-reconciler": "0.33.0",  // 정확한 버전
  "signal-exit": "^4",
  "wrap-ansi": "^9",
  "ansi-escapes": "^7",
  "ansi-styles": "^6",
  "widest-line": "^5",
  "cli-boxes": "^4",
  "chalk": "^5",
  "indent-string": "^5",
  "slice-ansi": "^7",
  "string-width": "^7"
},
"devDependencies": {
  "@types/react-reconciler": "0.32.3",
  "@types/lodash-es": "^4",
  "@types/signal-exit": "^3"
}
```

## 진행 체크리스트

- [x] Phase 1: `src/ink/*` 전체 복사 (48 파일)
- [x] Phase 2: `src/native-ts/yoga-layout/*` 복사 (color-diff, file-index 제외 — 미사용)
- [x] Phase 3: Stub 파일 생성 (bootstrap/state.ts + utils 10개)
- [x] Phase 4: 절대 경로 → 상대 경로 변환 (5 파일: root.ts, ink.tsx, renderer.ts, reconciler.ts, layout/yoga.ts)
- [x] Phase 5: `package.json` 의존성 추가 (19 runtime + 8 dev deps, ink/ink-spinner/ink-text-input 제거)
- [x] Phase 6: `npm install` 성공 (95 packages)
- [x] Phase 7: `tsconfig.json` 완화 (strict off, implicit any 허용)
- [x] Phase 8: `app.tsx` + `TextInput.tsx` import 경로 교체 (inline AlternateScreen 제거, fork의 것 사용)
- [x] Phase 9: `tsc` 빌드 성공 (exit 0, 31MB dist/)
- [x] Phase 10: 실행 smoke test — ENTER_ALT_SCREEN + SGR mouse tracking 정상 emit 확인

## 검증된 escape sequence

실행 로그에서 확인:
- `\x1b[?1049h\x1b[2J\x1b[H` — alt screen 진입 + 클리어 + 홈 (올바른 순서)
- `\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h` — SGR mouse tracking (click + drag + motion + extended)
- 종료 시 역순으로 cleanup: mouse disable → exit alt screen
- **Claude Code와 동일한 방식**

## 남은 사용자 검증

1. cafibot 실행 (`cafibot` 명령) → 정상 부팅 확인
2. 작업 중 마우스 드래그 → 드래그 구간이 앱에 selection으로 표시되는지 (mouse tracking 동작)
3. 드래그 중 중복 출력 발생 안 하는지 (근본 해결 확인)
4. iTerm 복사 시 Option 누르고 드래그 (Claude Code와 동일한 UX)
5. ESC로 종료 시 main screen 원상 복구되는지

## 경로 변환 규칙

파일 위치 기준 상대 경로 계산:
- `src/ink/*.ts` → `src/bootstrap/state.js` = `../bootstrap/state.js`
- `src/ink/components/*.tsx` → `src/bootstrap/state.js` = `../../bootstrap/state.js`
- `src/ink/*.ts` → `src/native-ts/yoga-layout/index.js` = `../native-ts/yoga-layout/index.js`

## 복구 포인트

문제 생기면:
1. `cafibot-ui/src/app.tsx`, `TextInput.tsx`만 복원하면 npm ink로 롤백 가능
2. `src/ink`, `src/native-ts`, `src/bootstrap`, `src/utils` 폴더 삭제하면 깨끗한 원상복구

## 실패 시 관찰 포인트

1. React Compiler runtime — `react/compiler-runtime` import 필요 시 react 19+ 확인
2. yoga-layout API 호환성 — `Yoga.DIRECTION_LTR` 등 enum 사용 확인
3. react-reconciler 버전 mismatch — 0.33.0 정확히 사용
4. ESM vs CJS — cafibot-ui는 `"type": "module"`, 모든 import 에 `.js` 확장자 필요

## Post-port Tasks (이식 완료 후 작업)

이식이 끝나고 중복 출력 문제 해결된 뒤 순차적으로 진행:

### 1. 메시지 렌더링 스페이싱 동일화
- Claude Code의 메시지 블록 구조 참조 (`marginY`, `paddingX`, 구분선)
- 현재 `MarkdownText`, bash 출력, tool result 렌더링을 Claude Code 스타일로 맞춤
- 참조: Claude Code 실제 UI 관찰 + `src/ink/components/Box.tsx`, `Text.tsx` 사용 패턴

### 2. 하이라이팅 동일화
- **파일 경로** 하이라이팅 (`foo/bar.py:123` 형태 감지 → 색상)
- **명령어** 하이라이팅 (bash 코드블록, 인라인 `` ` `` 코드)
- **파일명** 하이라이팅 (diff/edit 출력에서)
- 참조: Claude Code의 `src/ink/colorize.ts`, `render-to-screen.ts`, `searchHighlight.ts`

### 3. 폰트 크기 — 앱 제어 불가
- iTerm2 → Preferences → Profiles → Text → Font 에서 사용자가 직접 설정
- Claude Code도 동일하게 터미널 설정에 의존

### 4. 이모지/아이콘 간격
- 툴 호출 표시(`⏺ bash(...)`, `⎿ ...`) 패턴을 Claude Code 동일하게

### 5. 메시지 입력 반영 시점 (CafiBot 코어, UI 무관)
- **현재:** agent loop 전체 턴 종료 뒤 반영
- **목표:** Claude Code처럼 tool call 직후 (다음 LLM 턴 시작 전) stdin buffer 확인 후 pending 메시지 주입
- 수정 위치: `cafibot/loop.py` `_run_loop` — 각 tool call 완료 후 루프 반복 직전
- Python 작업이라 cafibot-ui 이식과 완전히 별개

### 6. ESC Interrupt 동작 동일화 (CafiBot 코어)
- **현재:** `agent.interrupted = True` 플래그만 세팅, loop 상단에서만 체크 — tool 실행 중 중단 안 됨
- **목표:** Claude Code처럼 AbortController 패턴으로 **즉시** 중단
  - LLM streaming 중단 (in-flight request abort)
  - tool 실행 중단 (subprocess kill, fetch abort)
  - agent loop의 모든 awaitable에 abortSignal 전파
- 참조: Claude Code의 `AbortController`, `combinedAbortSignal` 패턴
- 수정 위치:
  - `cafibot/llm_client.py` — stream 처리에 abort signal
  - `cafibot/tools.py` — subprocess timeout/kill 경로
  - `cafibot/loop.py` — 전역 abort context 관리
- Python 작업, cafibot-ui 이식과 별개
