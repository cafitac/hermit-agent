import { jsx as _jsx } from "react/jsx-runtime";
/**
 * TextInput
 *
 * Maintains a small, self-contained cursor model that is:
 * - grapheme-aware
 * - width-aware
 * - wrap-aware
 *
 * This deliberately keeps the input primitive simple and predictable instead of
 * trying to mimic every detail of Claude Code's private TUI.
 */
import { useCallback, useRef, useState } from 'react';
import Text from './ink/components/Text.js';
import Box from './ink/components/Box.js';
import useInput from './ink/hooks/use-input.js';
import { useDeclaredCursor } from './ink/hooks/use-declared-cursor.js';
import { stringWidth } from './ink/stringWidth.js';
const graphemeSegmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
function toGraphemes(text) {
    return Array.from(graphemeSegmenter.segment(text), ({ segment }) => segment);
}
function graphemeLength(text) {
    return toGraphemes(text).length;
}
function graphemeSlice(text, start, end) {
    return toGraphemes(text).slice(start, end).join('');
}
function buildWrappedPositions(text, wrapWidth) {
    const graphemes = toGraphemes(text);
    const positions = [{ offset: 0, line: 0, column: 0 }];
    const finiteWrap = Number.isFinite(wrapWidth) && wrapWidth > 0;
    let line = 0;
    let column = 0;
    for (let index = 0; index < graphemes.length; index += 1) {
        const grapheme = graphemes[index];
        if (grapheme === '\n') {
            line += 1;
            column = 0;
            positions.push({ offset: index + 1, line, column });
            continue;
        }
        const width = stringWidth(grapheme);
        if (finiteWrap && column > 0 && column + width > wrapWidth) {
            line += 1;
            column = 0;
        }
        column += width;
        positions.push({ offset: index + 1, line, column });
        if (finiteWrap && column >= wrapWidth) {
            line += 1;
            column = 0;
        }
    }
    return positions;
}
export function getCursorPositionForWrappedText(text, wrapWidth) {
    const positions = buildWrappedPositions(text, wrapWidth);
    const last = positions[positions.length - 1];
    return last ? { line: last.line, column: last.column } : { line: 0, column: 0 };
}
export function getWrappedLineCount(text, wrapWidth) {
    return getCursorPositionForWrappedText(text, wrapWidth).line + 1;
}
function moveCursorVertically(text, offset, wrapWidth, delta) {
    const positions = buildWrappedPositions(text, wrapWidth);
    const current = positions[Math.max(0, Math.min(offset, positions.length - 1))];
    if (!current)
        return offset;
    const targetLine = current.line + delta;
    if (targetLine < 0)
        return offset;
    const candidates = positions.filter(position => position.line === targetLine);
    if (candidates.length === 0)
        return offset;
    let selected = candidates[0];
    for (const candidate of candidates) {
        if (candidate.column <= current.column) {
            selected = candidate;
            continue;
        }
        break;
    }
    return selected.offset;
}
function TextInput({ value, placeholder = '', focus = true, onChange, onSubmit, wrapWidth, }) {
    const [, setTick] = useState(0);
    const valueRef = useRef(value);
    const offsetRef = useRef(graphemeLength(value));
    const onChangeRef = useRef(onChange);
    const onSubmitRef = useRef(onSubmit);
    onChangeRef.current = onChange;
    onSubmitRef.current = onSubmit;
    const previousValue = useRef(value);
    if (value !== previousValue.current) {
        valueRef.current = value;
        offsetRef.current = graphemeLength(value);
        previousValue.current = value;
    }
    const effectiveWrapWidth = wrapWidth ?? Number.POSITIVE_INFINITY;
    const beforeCursor = graphemeSlice(valueRef.current, 0, offsetRef.current);
    const cursorPosition = getCursorPositionForWrappedText(beforeCursor, effectiveWrapWidth);
    const setNodeRef = useDeclaredCursor({
        line: cursorPosition.line,
        column: cursorPosition.column,
        active: focus,
    });
    useInput(useCallback((input, key) => {
        if (key.pageUp || key.pageDown ||
            key.wheelUp || key.wheelDown ||
            (key.ctrl && (input === 'c' || input === 'd')) ||
            input === '\x03' || input === '\x04' ||
            key.tab || (key.shift && key.tab)) {
            return;
        }
        const currentValue = valueRef.current;
        const currentOffset = offsetRef.current;
        let nextValue = currentValue;
        let nextOffset = currentOffset;
        if ((key.shift && key.return) || (key.meta && key.return)) {
            nextValue = graphemeSlice(currentValue, 0, currentOffset) + '\n' + graphemeSlice(currentValue, currentOffset);
            nextOffset = currentOffset + 1;
        }
        else if (key.return) {
            onSubmitRef.current?.(currentValue);
            return;
        }
        else if (key.leftArrow) {
            nextOffset = Math.max(0, currentOffset - 1);
        }
        else if (key.rightArrow) {
            nextOffset = Math.min(graphemeLength(currentValue), currentOffset + 1);
        }
        else if (key.upArrow) {
            nextOffset = moveCursorVertically(currentValue, currentOffset, effectiveWrapWidth, -1);
        }
        else if (key.downArrow) {
            nextOffset = moveCursorVertically(currentValue, currentOffset, effectiveWrapWidth, 1);
        }
        else if (key.home) {
            nextOffset = 0;
        }
        else if (key.end) {
            nextOffset = graphemeLength(currentValue);
        }
        else if (key.backspace || key.delete) {
            if (currentOffset > 0) {
                nextValue = graphemeSlice(currentValue, 0, currentOffset - 1) + graphemeSlice(currentValue, currentOffset);
                nextOffset = currentOffset - 1;
            }
        }
        else if (input) {
            nextValue = graphemeSlice(currentValue, 0, currentOffset) + input + graphemeSlice(currentValue, currentOffset);
            nextOffset = currentOffset + graphemeLength(input);
        }
        const maxOffset = graphemeLength(nextValue);
        nextOffset = Math.max(0, Math.min(nextOffset, maxOffset));
        valueRef.current = nextValue;
        offsetRef.current = nextOffset;
        setTick(value => value + 1);
        if (nextValue !== currentValue) {
            onChangeRef.current(nextValue);
        }
    }, [effectiveWrapWidth]), { isActive: focus });
    const displayValue = valueRef.current;
    if (graphemeLength(displayValue) === 0 && placeholder) {
        return (_jsx(Box, { ref: setNodeRef, children: _jsx(Text, { dim: true, children: placeholder }) }));
    }
    return (_jsx(Box, { ref: setNodeRef, children: _jsx(Text, { children: displayValue }) }));
}
export default TextInput;
