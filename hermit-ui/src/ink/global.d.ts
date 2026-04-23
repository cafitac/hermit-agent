/**
 * Global type augmentations for the Claude Code Ink fork.
 */

declare module 'react/compiler-runtime' {
  export function c<T = unknown>(size: number): T[];
}

declare module 'bidi-js' {
  const bidi: any;
  export default bidi;
  export function getEmbeddingLevels(...args: any[]): any;
}

declare module '@alcalzone/ansi-tokenize' {
  export type AnsiCode = any;
  export type StyledChar = any;
  export function tokenize(input: string): any[];
  export function styledCharsFromTokens(tokens: any[]): any[];
  export function ansiCodesToString(codes: any[]): string;
  export function diffAnsiCodes(a: any[], b: any[]): any[];
  const _default: any;
  export default _default;
}

declare module 'diff' {
  export function diffLines(a: string, b: string, opts?: any): any[];
  export function diffWords(a: string, b: string, opts?: any): any[];
  export function diffChars(a: string, b: string, opts?: any): any[];
}

declare module 'highlight.js' {
  const hljs: any;
  export default hljs;
}

// React JSX intrinsic element augmentation (react-jsx automatic runtime).
declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'ink-root': any;
      'ink-box': any;
      'ink-text': any;
      'ink-link': any;
      'ink-raw-ansi': any;
      'ink-virtual-text': any;
    }
  }
}

declare global {
  const Bun:
    | {
        version: string;
        stringWidth?: (s: string, opts?: any) => number;
        wrapAnsi?: (s: string, cols: number, opts?: any) => string;
        [key: string]: any;
      }
    | undefined;

  // Fallback global JSX augmentation for legacy JSX transform.
  namespace JSX {
    interface IntrinsicElements {
      'ink-root': any;
      'ink-box': any;
      'ink-text': any;
      'ink-link': any;
      'ink-raw-ansi': any;
      'ink-virtual-text': any;
    }
  }
}

export {};
