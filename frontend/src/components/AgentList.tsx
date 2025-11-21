import { AgentStatus } from '../types';
import { AGENTS } from '../types';
import AgentCard from './AgentCard';

interface AgentListProps {
  agentStatuses: Record<string, AgentStatus>;
  selectedAgent: string | null;
  onSelectAgent: (agentId: string) => void;
  onRunReport: () => void;
  autoRun: boolean;
  onToggleAutoRun: () => void;
}

export default function AgentList({ agentStatuses, selectedAgent, onSelectAgent, onRunReport, autoRun, onToggleAutoRun }: AgentListProps) {
  return (
    <div className="h-full flex flex-col matrix-panel matrix-border">
      <div className="p-4 border-b border-matrix-green/30">
        <h2 className="text-lg font-bold text-matrix-green matrix-glow text-center">GWEN</h2>
        <div className="text-xs text-matrix-green/60 mt-1 text-center">Multi-Agent Orchestration System</div>
        <button
          onClick={onRunReport}
          className="w-full mt-3 matrix-button text-sm font-semibold"
        >
          ▶ RETRIEVE STATUS
        </button>
        <button
          onClick={onToggleAutoRun}
          className={`w-full mt-2 text-xs font-semibold px-3 py-1.5 rounded border transition-colors ${
            autoRun 
              ? 'bg-matrix-green/20 border-matrix-green text-matrix-green' 
              : 'bg-matrix-dark border-matrix-green/30 text-matrix-green/60 hover:border-matrix-green/50'
          }`}
        >
          {autoRun ? '● AUTO-RETRIEVE: ON (5min)' : '○ AUTO-RETRIEVE: OFF'}
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto space-y-2 p-2">
        {AGENTS.map((agent) => {
          const status = agentStatuses[agent.id];
          const state = status?.state || 'idle';
          
          return (
            <AgentCard
              key={agent.id}
              name={agent.name}
              logo={agent.logo}
              state={state}
              color={agent.color}
              isSelected={selectedAgent === agent.id}
              onClick={() => onSelectAgent(agent.id)}
            />
          );
        })}
      </div>
    </div>
  );
}
