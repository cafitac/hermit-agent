/**
 * TextInput — grapheme-aware, wrap-aware terminal text input.
 *
 * Architecture: WrapModel is a pure (immutable-after-construction) class that
 * owns the single wrap algorithm. Both cursor positioning and visual rendering
 * derive from the same WrapModel instance, so they can never drift out of sync.
 *
 * Previously the cursor was computed from a sliced substring while rendering
 * used Ink's global textWrap setting — two separate algorithms that could
 * silently diverge and misplace the cursor on wrapped lines.
 */

import React, { useCallback, useRef, useState } from 'react';
import Text from './ink/components/Text.js';
import Box from './ink/components/Box.js';
import useInput from './ink/hooks/use-input.js';
import { useDeclaredCursor } from './ink/hooks/use-declared-cursor.js';
import { stringWidth } from './ink/stringWidth.js';

// ─── Grapheme primitives ───────────────────────────────────────────────────

const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });

function toGraphemes(text: string): string[] {
  return Array.from(segmenter.segment(text), s => s.segment);
}

// ─── WrapModel ────────────────────────────────────────────────────────────

type CursorPos = { line: number; column: number };
type WrapPos  = CursorPos & { offset: number };

/**
 * Pure wrap model — immutable after construction.
 *
 * _positions[i] = cursor state after placing grapheme i-1.
 * _positions[0] = initial state (before any grapheme).
 *
 * Both cursorAt() and displayLines use the same _positions array, so visual
 * rows and cursor rows are guaranteed identical without any synchronisation.
 */
class WrapModel {
  private readonly _graphemes: readonly string[];
  private readonly _positions: readonly WrapPos[];

  constructor(readonly text: string, readonly wrapWidth: number) {
    this._graphemes = toGraphemes(text);
    this._positions = this._build();
  }

  private _build(): WrapPos[] {
    const positions: WrapPos[] = [{ offset: 0, line: 0, column: 0 }];
    const finite = Number.isFinite(this.wrapWidth) && this.wrapWidth > 0;
    let line = 0;
    let column = 0;

    for (let i = 0; i < this._graphemes.length; i++) {
      const g = this._graphemes[i]!;

      if (g === '\n') {
        line += 1;
        column = 0;
        positions.push({ offset: i + 1, line, column });
        continue;
      }

      const w = stringWidth(g);
      if (finite && column > 0 && column + w > this.wrapWidth) {
        line += 1;
        column = 0;
      }
      column += w;
      positions.push({ offset: i + 1, line, column });
      if (finite && column >= this.wrapWidth) {
        line += 1;
        column = 0;
      }
    }

    return positions;
  }

  /** Cursor position after the grapheme at grapheme-offset `offset`. */
  cursorAt(offset: number): CursorPos {
    const clamped = Math.max(0, Math.min(offset, this._positions.length - 1));
    const p = this._positions[clamped]!;
    return { line: p.line, column: p.column };
  }

  /** Total visual line count. */
  get lineCount(): number {
    return (this._positions[this._positions.length - 1]?.line ?? 0) + 1;
  }

  /**
   * Text split into visual rows. Row i maps directly to cursor relativeY=i.
   * '\n' chars are separators — excluded from row content so they don't
   * inject a literal newline inside the rendered Text node.
   */
  get displayLines(): string[] {
    if (this._graphemes.length === 0) return [''];

    const rowBuckets = new Map<number, string[]>();
    for (let i = 0; i < this._graphemes.length; i++) {
      const g = this._graphemes[i]!;
      if (g === '\n') continue;
      const row = this._positions[i + 1]!.line;
      let bucket = rowBuckets.get(row);
      if (!bucket) rowBuckets.set(row, (bucket = []));
      bucket.push(g);
    }

    return Array.from({ length: this.lineCount }, (_, i) =>
      (rowBuckets.get(i) ?? []).join('')
    );
  }

  /**
   * Move cursor up or down one visual line, preserving column.
   * Returns the original offset if movement would leave the text bounds.
   */
  moveCursorVertically(offset: number, delta: -1 | 1): number {
    const clamped = Math.max(0, Math.min(offset, this._positions.length - 1));
    const current = this._positions[clamped]!;
    const targetLine = current.line + delta;
    if (targetLine < 0) return offset;

    // Walk positions on targetLine; keep the last one whose column ≤ current
    // column so the cursor tracks the original horizontal position.
    let selected: WrapPos | undefined;
    for (const p of this._positions) {
      if (p.line < targetLine) continue;
      if (p.line > targetLine) break;
      if (p.column <= current.column) selected = p;
    }
    return selected?.offset ?? offset;
  }
}

// ─── Public surface (used by uiModel.ts, SmartInput) ──────────────────────

export function getCursorPositionForWrappedText(
  text: string,
  wrapWidth: number,
): CursorPos {
  // Create a model for the full text; cursor at end = position after last grapheme.
  const model = new WrapModel(text, wrapWidth);
  return model.cursorAt(Number.POSITIVE_INFINITY);
}

export function getWrappedLineCount(text: string, wrapWidth: number): number {
  return new WrapModel(text, wrapWidth).lineCount;
}

// ─── Component ────────────────────────────────────────────────────────────

interface TextInputProps {
  value: string;
  placeholder?: string;
  focus?: boolean;
  onChange: (value: string) => void;
  onSubmit?: (value: string) => void;
  wrapWidth?: number;
}

function TextInput({
  value,
  placeholder = '',
  focus = true,
  onChange,
  onSubmit,
  wrapWidth,
}: TextInputProps) {
  const [, setTick] = useState(0);

  // Mutable refs hold the authoritative value and cursor offset so the
  // useInput callback never closes over stale state. onChange/onSubmit are
  // also ref-tracked to keep the useCallback dep array stable (only wrapWidth
  // changes should re-create the handler).
  const valueRef    = useRef(value);
  const offsetRef   = useRef(toGraphemes(value).length);
  const onChangeRef = useRef(onChange);
  const onSubmitRef = useRef(onSubmit);
  onChangeRef.current = onChange;
  onSubmitRef.current = onSubmit;

  // Sync external value (e.g. history navigation from parent); move cursor to end.
  if (value !== valueRef.current) {
    valueRef.current = value;
    offsetRef.current = toGraphemes(value).length;
  }

  const effectiveWrapWidth = wrapWidth ?? Number.POSITIVE_INFINITY;

  // One model per render — positions computed once, shared by cursorAt and displayLines.
  const model = new WrapModel(valueRef.current, effectiveWrapWidth);
  const cursorPos = model.cursorAt(offsetRef.current);

  const setNodeRef = useDeclaredCursor({
    line: cursorPos.line,
    column: cursorPos.column,
    active: focus,
  });

  useInput(useCallback((input: string, key: any) => {
    // Pass-through: let parent handle scroll, exit, and tab-completion.
    if (
      key.pageUp || key.pageDown ||
      (key as any).wheelUp || (key as any).wheelDown ||
      (key.ctrl && (input === 'c' || input === 'd')) ||
      input === '\x03' || input === '\x04' ||
      key.tab || (key.shift && key.tab)
    ) return;

    const graphemes  = toGraphemes(valueRef.current);
    let nextGraphemes = graphemes;
    let nextOffset    = offsetRef.current;

    if ((key.shift && key.return) || (key.meta && key.return)) {
      nextGraphemes = [...graphemes.slice(0, nextOffset), '\n', ...graphemes.slice(nextOffset)];
      nextOffset += 1;
    } else if (key.return) {
      onSubmitRef.current?.(valueRef.current);
      return;
    } else if (key.leftArrow) {
      nextOffset = Math.max(0, nextOffset - 1);
    } else if (key.rightArrow) {
      nextOffset = Math.min(graphemes.length, nextOffset + 1);
    } else if (key.upArrow || key.downArrow) {
      // Re-create model with current value (valueRef may have changed since render).
      nextOffset = new WrapModel(valueRef.current, effectiveWrapWidth)
        .moveCursorVertically(nextOffset, key.upArrow ? -1 : 1);
    } else if (key.home) {
      nextOffset = 0;
    } else if (key.end) {
      nextOffset = graphemes.length;
    } else if (key.backspace || key.delete) {
      if (nextOffset > 0) {
        nextGraphemes = [...graphemes.slice(0, nextOffset - 1), ...graphemes.slice(nextOffset)];
        nextOffset -= 1;
      }
    } else if (input) {
      const inputGraphemes = toGraphemes(input);
      nextGraphemes = [...graphemes.slice(0, nextOffset), ...inputGraphemes, ...graphemes.slice(nextOffset)];
      nextOffset += inputGraphemes.length;
    }

    nextOffset = Math.max(0, Math.min(nextOffset, nextGraphemes.length));
    const nextValue = nextGraphemes.join('');
    valueRef.current = nextValue;
    offsetRef.current = nextOffset;
    setTick(t => t + 1);
    if (nextValue !== graphemes.join('')) onChangeRef.current(nextValue);
  }, [effectiveWrapWidth]), { isActive: focus });

  if (!valueRef.current && placeholder) {
    return (
      <Box ref={setNodeRef}>
        <Text dim>{placeholder}</Text>
      </Box>
    );
  }

  // Each display line renders as a separate Text row in a column Box.
  // Row i maps to cursor relativeY=i — derived from the same model.displayLines
  // as model.cursorAt(), so visual rows and cursor rows are always identical.
  return (
    <Box ref={setNodeRef} flexDirection="column">
      {model.displayLines.map((line, i) => (
        <Text key={i}>{line}</Text>
      ))}
    </Box>
  );
}

export default TextInput;
