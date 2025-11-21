// Agent state values
export type AgentStateValue = 'idle' | 'thinking' | 'completed' | 'warning' | 'error';

// Agent status interface matching backend AgentStatus model
export interface AgentStatus {
  agent_name: string;
  state: AgentStateValue;
  start_time: string | null;
  end_time: string | null;
  messages: string[];
  raw_output: Record<string, any> | null;
  error_message: string | null;
}

// Agent summary from orchestrator report
export interface AgentSummary {
  agent_name: string;
  status: string;
  summary: string;
  key_metrics: Record<string, any>;
  execution_time: number;
}

// Orchestrator report from /retrieve-status
export interface OrchestratorReport {
  execution_id: string;
  start_time: string;
  end_time: string;
  total_duration: number;
  agent_summaries: AgentSummary[];
  overall_status: string;
  errors: string[];
}

// Agent logs from /agent-logs/{agent_name}
export interface AgentLogs {
  agent_name: string;
  state: AgentStateValue;
  execution: {
    start_time: string | null;
    end_time: string | null;
    duration_seconds: number | null;
  };
  messages: string[];
  message_count: number;
  raw_output: Record<string, any> | null;
  error: string | null;
  dashboard_display: {
    color: string;
    icon: string;
    last_message: string | null;
  };
}

// Agent configuration for UI
export interface AgentConfig {
  id: string;
  name: string;
  logo: string; // Path to logo SVG
  color: string; // Brand color for accents
}

// Available agents in order
export const AGENTS: AgentConfig[] = [
  { id: 'CloudflareAgent', name: 'Cloudflare', logo: '/logos/cloudflare.svg', color: '#F38020' },
  { id: 'AWSAgent', name: 'AWS', logo: '/logos/aws.svg', color: '#FF9900' },
  { id: 'AzureAgent', name: 'Azure', logo: '/logos/azure.svg', color: '#0078D4' },
  { id: 'GCPAgent', name: 'GCP', logo: '/logos/gcp.svg', color: '#4285F4' },
  { id: 'GitHubAgent', name: 'GitHub', logo: '/logos/github.svg', color: '#238636' },
  { id: 'DatadogAgent', name: 'Datadog', logo: '/logos/datadog.svg', color: '#632CA6' },
  { id: 'AtlassianAgent', name: 'Atlassian', logo: '/logos/atlassian.svg', color: '#0052CC' },
];
