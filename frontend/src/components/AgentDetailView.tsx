import { AgentStatus, AgentSummary } from '../types';
import { AGENTS } from '../types';

interface AgentDetailViewProps {
  agentId: string;
  status: AgentStatus | null;
  summary: AgentSummary | null;
}

// Format metric values in a human-readable way
const formatMetricValue = (value: any): string => {
  if (value === null || value === undefined) return 'N/A';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    if (value.length === 0) return 'None';
    // For arrays, show items in a more readable format
    return value.map(item => 
      typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)
    ).join('\n');
  }
  if (typeof value === 'object') {
    // Special handling for status objects
    if ('indicator' in value && 'description' in value) {
      return `${value.description || value.indicator}`;
    }
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

// Format metric key to be more readable
const formatMetricKey = (key: string): string => {
  return key
    .replace(/_/g, ' ')
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

export default function AgentDetailView({ agentId, status, summary }: AgentDetailViewProps) {
  const agent = AGENTS.find(a => a.id === agentId);
  
  if (!agent) {
    return (
      <div className="h-full matrix-panel matrix-border flex items-center justify-center">
        <div className="text-matrix-green/60">Agent not found</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col matrix-panel matrix-border overflow-hidden">
      <div className="p-6 border-b border-matrix-green/30">
        <div className="flex items-center gap-4 mb-4">
          <div 
            className="w-16 h-16 rounded-lg flex-shrink-0 flex items-center justify-center p-3 bg-white"
            style={{ border: `2px solid ${agent.color}` }}
          >
            <img 
              src={agent.logo} 
              alt={`${agent.name} logo`}
              className="w-full h-full object-contain"
              onError={(e) => {
                // Fallback to colored letter if logo fails to load
                const target = e.currentTarget;
                target.style.display = 'none';
                const parent = target.parentElement;
                if (parent) {
                  parent.style.backgroundColor = agent.color + '20';
                  parent.innerHTML = `<span class="text-2xl font-bold" style="color: ${agent.color}">${agent.name[0]}</span>`;
                }
              }}
            />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-matrix-green matrix-glow">
              {agent.name}
            </h1>
            <div className="text-sm text-matrix-green/60 mt-1">{agent.id}</div>
          </div>
        </div>
        
        {status && (
          <div className={`inline-block px-3 py-1 rounded text-sm ${
            status.state === 'completed' ? 'status-completed' :
            status.state === 'thinking' ? 'status-thinking animate-pulse' :
            status.state === 'warning' ? 'status-warning' :
            status.state === 'error' ? 'status-error' :
            'status-idle'
          }`}>
            {status.state.toUpperCase()}
          </div>
        )}
      </div>
      
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {summary && (
          <>
            <div className="matrix-panel matrix-border p-4">
              <h3 className="text-lg font-semibold text-matrix-green mb-2">Summary</h3>
              
              {/* Prominent Status Description */}
              {summary.key_metrics?.status && (
                <div className={`mb-3 p-2 rounded border text-sm font-medium ${
                  summary.status === 'operational' ? 'bg-green-500/10 border-green-500/30 text-green-400' :
                  summary.status === 'minor' || summary.status === 'warning' ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400' :
                  summary.status === 'major' || summary.status === 'error' ? 'bg-red-500/10 border-red-500/30 text-red-400' :
                  'bg-gray-500/10 border-gray-500/30 text-gray-400'
                }`}>
                  {(summary.key_metrics.status as any)?.description || 
                    (summary.status === 'operational' ? 'All Systems Operational' :
                     summary.status === 'minor' ? 'Minor Issues Detected' :
                     summary.status === 'major' ? 'Major Outage' :
                     summary.status === 'warning' ? 'Performance Degraded' :
                     summary.status === 'error' ? 'Service Disruption' :
                     'Status Unknown')}
                </div>
              )}
              
              <p className="text-sm text-matrix-green/80">{summary.summary}</p>
              <div className="text-xs text-matrix-green/50 mt-2">
                Status: {summary.status} | Execution: {summary.execution_time.toFixed(2)}s
              </div>
            </div>
            
            {Object.keys(summary.key_metrics).length > 0 && (
              <div className="matrix-panel matrix-border p-4">
                <h3 className="text-lg font-semibold text-matrix-green mb-3">Key Metrics</h3>
                <div className="space-y-2">
                  {Object.entries(summary.key_metrics)
                    .filter(([key]) => key !== 'status' && key !== 'current_status')
                    .map(([key, value]) => (
                    <div key={key} className="bg-matrix-dark/50 p-3 rounded border border-matrix-green/20">
                      <div className="text-sm text-matrix-green/60 mb-1">
                        {formatMetricKey(key)}
                      </div>
                      <div className="text-matrix-green font-mono">
                        {typeof value === 'object' || Array.isArray(value) ? (
                          <pre className="text-xs overflow-x-auto whitespace-pre-wrap">
                            {formatMetricValue(value)}
                          </pre>
                        ) : (
                          formatMetricValue(value)
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
        
        {status?.raw_output && (
          <div className="matrix-panel matrix-border p-4">
            <h3 className="text-lg font-semibold text-matrix-green mb-3">Raw Output</h3>
            <pre className="text-xs text-matrix-green/70 overflow-x-auto bg-matrix-darker p-3 rounded border border-matrix-green/20">
              {JSON.stringify(status.raw_output, null, 2)}
            </pre>
          </div>
        )}
        
        {status?.error_message && (
          <div className="matrix-panel border-red-500/50 p-4 bg-red-500/5">
            <h3 className="text-lg font-semibold text-red-400 mb-2">ERROR</h3>
            <div className="text-sm text-red-300/80">{status.error_message}</div>
          </div>
        )}
        
        {!status && !summary && (
          <div className="text-center text-matrix-green/40 py-12">
            No data available for this agent
          </div>
        )}
      </div>
    </div>
  );
}
