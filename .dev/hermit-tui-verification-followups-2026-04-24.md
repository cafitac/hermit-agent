# Hermit TUI Verification Follow-Ups

Date: 2026-04-24

Scope: repo-local `hermit-ui/` packaged TUI only

---

## Current status

The recent TUI passes fixed these issues:

- packaged startup now seeds `version` and `model` on the first frame
- multiline input is edited as one buffer instead of `preview + last-line-only`
- `Shift+Enter` no longer forces the user into a non-editable earlier-line state
- main prompt wrap width is handled separately from generic input width
- local stdin debug side-effect logging to `/tmp/hermit-stdin.log` was removed
- npm packaging now ships `hermit-ui/dist/*` instead of vendored `node_modules`

Validated during the recent pass:

- `cd hermit-ui && npm run build && node --test tests/*.test.mjs`
- `npm run test:npm-wrapper`
- startup smoke via `node npm-wrapper/bin/hermit.js --no-update-check`
- basic roundtrip smoke: prompt -> running -> completed -> assistant reply

---

## Remaining verification

These are still worth checking manually in the live TUI.

### 1. Extended multiline editing

Need to verify:

- type multiple wrapped lines with `Shift+Enter`
- move the cursor back into earlier lines
- insert/delete in the middle of the buffer
- confirm cursor position stays visually aligned after several edits

Reason:

- the buffer ownership model was corrected, but the final confidence still depends on live cursor behavior under repeated edits

### 2. Soft-wrap stress cases

Need to verify:

- very long single-line input that wraps across several visual lines
- moving left/right across wrap boundaries
- moving up/down across wrap boundaries after mid-line edits
- CJK / emoji width cases in wrapped input

Reason:

- wrap math is now much closer to OMX behavior, but the final renderer still depends on Ink layout and declared cursor placement

### 3. Scroll and input interaction

Need to verify:

- long assistant output, then immediate user typing
- scroll up with `PgUp` / wheel, then return to bottom and continue typing
- background/foreground transitions while the output area is large

Reason:

- input fixes were prioritized; the scroll path itself was not deeply reworked in this round

### 4. IME composition confidence pass

Need to verify:

- Korean IME composition during multiline editing
- composition across wrapped lines
- backspace behavior immediately after composition commit

Reason:

- the local IME workaround remains in place, but this round did not add new IME-specific tests

---

## Known acceptable limitations

These are not current blockers.

- the gateway/session divider line may update after the first frame as bridge status arrives
- the permission status row can still change shortly after startup as the bridge sends current mode
- this pass intentionally did not rewrite `hermit-ui/src/ink/*`

---

## Recommended next step

Do this before any deeper TUI refactor:

1. Run one manual verification pass covering the four sections above.
2. Capture any remaining reproduction as:
   - exact keys pressed
   - whether input was single-line or multiline
   - whether IME was active
   - whether the screen was already scrolled
3. Only if a bug remains after that, inspect `hermit-ui/src/ink/hooks/use-declared-cursor.ts` and the surrounding Ink text layout path.

---

## Guardrail for future work

If another input bug appears, prefer this order:

1. compare with OMX behavior first
2. keep one full-buffer input model
3. fix prompt/wrap/cursor geometry before touching the Ink fork
4. only then consider `src/ink` changes

Do not reintroduce:

- split multiline preview/edit state
- startup placeholders that wait for bridge readiness when static hints are already available
- packaged `hermit-ui/node_modules` in the npm tarball
