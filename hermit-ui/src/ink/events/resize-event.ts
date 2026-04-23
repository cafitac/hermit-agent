/**
 * Stub — ResizeEvent type for terminal resize dispatch.
 */

export interface ResizeEvent {
  readonly type: 'resize';
  readonly columns: number;
  readonly rows: number;
}
