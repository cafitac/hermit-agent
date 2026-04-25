/**
 * Shared TypeScript interfaces and constants for HermitAgent UI components.
 */

export interface ModalAction {
  key: string;
  label: string;
}

export interface ModalProps {
  title: string;
  body: string;
  actions: ModalAction[];
  onAction: (key: string) => void;
}

export interface SmartInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  placeholder?: string;
  commands: Record<string, string>;  // { "/help": "Get help..." }
}

export interface AgentStatus {
  version?: string;
  model?: string;
  session_id?: string;
  session_min?: number;
  ctx_pct?: number;
  tokens?: number;
  turns?: number;
  permission?: string;
  auto_agents?: number;
  modified_files?: number;
  cwd?: string;
}

export interface OutputLine {
  type: 'user' | 'tool_use' | 'tool_result' | 'assistant' | 'system' | 'timer' | 'error';
  text?: string;
  name?: string;
  detail?: string;
  is_error?: boolean;
  elapsed_s?: number;
}

export interface AgentMessage {
  type: string;
  content?: string;
  token?: string;
  name?: string;
  detail?: string;
  message?: string;
  is_error?: boolean;
  tool?: string;
  summary?: string;
  options?: string[];
  [key: string]: unknown;
}

export interface PermissionAsk {
  tool: string;
  summary: string;
  options: string[];
}

export const PERM_LABELS: Record<string, string> = {
  yes: 'Yes',
  always: 'Yes, and always allow',
  always_allow: 'Yes, and always allow',
  no: 'No',
  no_feedback: 'No, and tell Claude why...',
};

export interface SessionEntry {
  session_id: string;
  turn_count: number;
  age_str: string;
  preview: string;
  model: string;
}

export interface ScrollBoxProps {
  lines: OutputLine[];
  streamBuf: string;
  isRunning: boolean;
  backgrounded: boolean;
  bgNotification: string | null;
  lastTool: string;
  taskStart: number;
  toolCount: number;
  progressMsg: string;
}

export interface HistoryViewerProps {
  lines: OutputLine[];
  onClose: () => void;
}
