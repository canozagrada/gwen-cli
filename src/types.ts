// Core types for GWEN TUI system

export interface AgentConfig {
  name: string;
  version: string;
  description: string;
  author?: string;
  timeout?: number;
}

export interface AgentContext {
  log: (message: string, level?: 'info' | 'warn' | 'error' | 'success') => void;
  config: AgentConfig;
}

export interface Agent {
  run: (config: AgentConfig, context: AgentContext) => Promise<void>;
}

export interface LogEntry {
  timestamp: Date;
  level: 'info' | 'warn' | 'error' | 'success' | 'system';
  message: string;
  source?: string;
}

export interface Command {
  name: string;
  description: string;
  aliases?: string[];
  execute: (args: string[]) => Promise<void>;
}

export interface AgentResult {
  name: string;
  status: string;
  summary?: string;
  key_metrics?: any;
  messages?: string[];
  execution_time?: number;
  state?: string;
  error?: string;
  raw_output?: any;
}

export interface DashboardAgent {
  name: string;
  status: string;
  summary: string;
  current_incidents?: number;
  recent_incidents?: number;
  isExecuting?: boolean;
}

export type ViewMode = 'main' | 'detail';

export interface AppState {
  inputValue: string;
  showCommandPalette: boolean;
  selectedCommandIndex: number;
  isExecuting: boolean;
  currentAgent?: string;
  scrollOffset: number;
  viewMode: ViewMode;
  agentResults: AgentResult[];
  selectedAgentIndex: number;
  dashboardAgents: DashboardAgent[];
}
