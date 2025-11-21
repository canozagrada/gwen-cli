import { AgentLogs as AgentLogsType } from '../types';

interface AgentLogsProps {
  logs: AgentLogsType | null;
  isLoading: boolean;
}

export default function AgentLogs({ logs, isLoading }: AgentLogsProps) {
  if (isLoading) {
    return (
      <div className="h-full matrix-panel matrix-border flex items-center justify-center">
        <div className="text-matrix-green/60 animate-pulse">Loading logs...</div>
      </div>
    );
  }

  if (!logs) {
    return (
      <div className="h-full matrix-panel matrix-border flex items-center justify-center">
        <div className="text-matrix-green/60">Select an agent to view logs</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col matrix-panel matrix-border">
      <div className="p-4 border-b border-matrix-green/30">
        <h2 className="text-sm font-bold text-matrix-green matrix-glow">
          {logs.agent_name} LOGS
        </h2>
        <div className="text-xs text-matrix-green/60 mt-1">
          {logs.execution.duration_seconds 
            ? `Completed in ${logs.execution.duration_seconds.toFixed(2)}s`
            : 'Running...'}
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-1 font-mono text-xs">
        {logs.messages.length === 0 ? (
          <div className="text-matrix-green/40 italic">No messages yet</div>
        ) : (
          logs.messages.map((message, idx) => (
            <div key={idx} className="text-matrix-green/80">
              <span className="text-matrix-green/40">&gt;</span> {message}
            </div>
          ))
        )}
        
        {logs.error && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded">
            <div className="text-red-400 font-semibold">ERROR:</div>
            <div className="text-red-300/80 text-xs mt-1">{logs.error}</div>
          </div>
        )}
      </div>
    </div>
  );
}
