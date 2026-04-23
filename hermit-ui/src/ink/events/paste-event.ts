/**
 * Stub — Claude Code's source doesn't include paste-event.ts in the export
 * we received. Provides the PasteEvent type that event-handlers.ts imports.
 */

export interface PasteEvent {
  readonly type: 'paste';
  readonly data: string;
}
