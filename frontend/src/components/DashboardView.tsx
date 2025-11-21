import { OrchestratorReport } from '../types';

interface DashboardViewProps {
  report: OrchestratorReport | null;
  isLoading: boolean;
}

// Format metric values in a human-readable way
const formatMetricValue = (value: any): string => {
  if (value === null || value === undefined) return 'N/A';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return value.toLocaleString();
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    if (value.length === 0) return 'None';
    if (value.length <= 3) return value.join(', ');
    return `${value.length} items`;
  }
  if (typeof value === 'object') {
    // Special handling for status objects
    if ('indicator' in value && 'description' in value) {
      return `${value.description || value.indicator}`;
    }
    // For objects, show a summary instead of full JSON
    const keys = Object.keys(value);
    if (keys.length === 0) return 'Empty';
    if (keys.length === 1) return `${keys[0]}: ${formatMetricValue(value[keys[0]])}`;
    return `${keys.length} properties`;
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

export default function DashboardView({ report, isLoading }: DashboardViewProps) {
  if (isLoading) {
    return (
      <div className="h-full matrix-panel matrix-border flex items-center justify-center">
        <div className="text-matrix-green animate-pulse text-lg">
          Running orchestrator report...
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="h-full matrix-panel matrix-border flex flex-col items-center justify-center">
        <div className="text-matrix-green/60 text-lg mb-4">No report data available</div>
        <div className="text-matrix-green/40 text-sm">Select an agent or wait for next update</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col matrix-panel matrix-border overflow-hidden">
      <div className="p-6 border-b border-matrix-green/30">
        <h1 className="text-2xl font-bold text-matrix-green matrix-glow">
          ORCHESTRATOR DASHBOARD
        </h1>
        <div className="text-sm text-matrix-green/60 mt-2">
          Execution ID: {report.execution_id}
        </div>
        <div className="text-sm text-matrix-green/60">
          Duration: {report.total_duration.toFixed(2)}s
        </div>
        <div className={`text-sm mt-2 inline-block px-3 py-1 rounded ${
          report.overall_status === 'success' ? 'status-completed' :
          report.overall_status === 'warning' ? 'status-warning' :
          'status-error'
        }`}>
          {report.overall_status.toUpperCase()}
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {report.agent_summaries
          .sort((a, b) => {
            // Sort non-operational services to the top
            const aOperational = a.status === 'operational';
            const bOperational = b.status === 'operational';
            if (aOperational === bOperational) return 0;
            return aOperational ? 1 : -1; // Non-operational first
          })
          .map((summary) => {
          // Extract status info from key_metrics if available
          const statusInfo = summary.key_metrics?.status as any;
          const statusDescription = statusInfo?.description || 
            (summary.status === 'operational' ? 'All Systems Operational' :
             summary.status === 'minor' ? 'Minor Issues Detected' :
             summary.status === 'major' ? 'Major Outage' :
             summary.status === 'warning' ? 'Performance Degraded' :
             summary.status === 'error' ? 'Service Disruption' :
             'Status Unknown');
          
          return (
          <div key={summary.agent_name} className="matrix-panel matrix-border p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold text-matrix-green">
                {summary.agent_name.replace('Agent', '')}
              </h3>
              <div className={`text-xs px-2 py-1 rounded ${
                summary.status === 'operational' ? 'status-completed' :
                summary.status === 'minor' || summary.status === 'warning' ? 'status-warning' :
                summary.status === 'major' || summary.status === 'error' ? 'status-error' :
                'status-idle'
              }`}>
                {summary.status}
              </div>
            </div>

            {/* Prominent Status Description */}
            <div className={`mb-3 p-2 rounded border text-sm font-medium ${
              summary.status === 'operational' ? 'bg-green-500/10 border-green-500/30 text-green-400' :
              summary.status === 'minor' || summary.status === 'warning' ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400' :
              summary.status === 'major' || summary.status === 'error' ? 'bg-red-500/10 border-red-500/30 text-red-400' :
              'bg-gray-500/10 border-gray-500/30 text-gray-400'
            }`}>
              {statusDescription}
            </div>
            
            <p className="text-sm text-matrix-green/80 mb-3">{summary.summary}</p>
            
            {Object.keys(summary.key_metrics).length > 0 && (
              <div className="grid grid-cols-2 gap-2 text-xs">
                {Object.entries(summary.key_metrics)
                  .filter(([key]) => key !== 'status' && key !== 'current_status')
                  .map(([key, value]) => (
                  <div key={key} className="bg-matrix-dark/50 p-2 rounded border border-matrix-green/20">
                    <div className="text-matrix-green/60">{formatMetricKey(key)}</div>
                    <div className="text-matrix-green font-semibold mt-1">
                      {formatMetricValue(value)}
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            <div className="text-xs text-matrix-green/50 mt-2">
              Execution: {summary.execution_time.toFixed(2)}s
            </div>
          </div>
          );
        })}
        
        {report.errors.length > 0 && (
          <div className="matrix-panel border-red-500/50 p-4 bg-red-500/5">
            <h3 className="text-lg font-semibold text-red-400 mb-2">ERRORS</h3>
            {report.errors.map((error, idx) => (
              <div key={idx} className="text-sm text-red-300/80 mb-1">
                • {error}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
