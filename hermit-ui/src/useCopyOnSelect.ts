/**
 * useCopyOnSelect — auto-copy-on-selection hook for the Ink UI.
 *
 * Auto-copies the selection to the clipboard when the user finishes dragging
 * (mouse-up with a non-empty selection). Mirrors iTerm2's "Copy on selection".
 * Because mouse tracking is enabled, the terminal's native Edit > Copy finds
 * no selection of its own — this hook makes Cmd+C a no-op that still yields
 * the right content because the clipboard was already written on mouse-up.
 *
 * Stripped of Claude Code's theme + global config dependencies:
 * - Always enabled (no copyOnSelect config toggle)
 * - No theme provider hook
 */

import { useEffect, useRef } from 'react';
import type { useSelection } from './ink/hooks/use-selection.js';

type Selection = ReturnType<typeof useSelection>;

export function useCopyOnSelect(
  selection: Selection,
  isActive: boolean,
  onCopied?: (text: string) => void,
): void {
  const copiedRef = useRef(false);
  const onCopiedRef = useRef(onCopied);
  onCopiedRef.current = onCopied;

  useEffect(() => {
    if (!isActive) return;

    const unsubscribe = selection.subscribe(() => {
      const sel = selection.getState();
      const has = selection.hasSelection();
      if (sel?.isDragging) {
        copiedRef.current = false;
        return;
      }
      if (!has) {
        copiedRef.current = false;
        return;
      }
      if (copiedRef.current) return;

      const text = selection.copySelectionNoClear();
      if (!text || !text.trim()) {
        copiedRef.current = true;
        return;
      }
      copiedRef.current = true;
      onCopiedRef.current?.(text);
    });
    return unsubscribe;
  }, [isActive, selection]);
}
