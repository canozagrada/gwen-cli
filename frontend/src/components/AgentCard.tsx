import { AgentStateValue } from '../types';

interface AgentCardProps {
  name: string;
  logo: string;
  state: AgentStateValue;
  color: string;
  isSelected: boolean;
  onClick: () => void;
}

export default function AgentCard({ name, logo, state, color, isSelected, onClick }: AgentCardProps) {
  const stateClasses = {
    idle: 'status-idle',
    thinking: 'status-thinking animate-pulse',
    completed: 'status-completed',
    warning: 'status-warning',
    error: 'status-error',
  };

  return (
    <button
      onClick={onClick}
      className={`
        w-full p-4 matrix-panel matrix-border flex items-center gap-3
        hover:bg-matrix-gray/30 transition-colors
        ${isSelected ? 'ring-2 ring-matrix-green' : ''}
      `}
    >
      {/* Logo image */}
      <div 
        className="w-10 h-10 rounded flex-shrink-0 flex items-center justify-center p-2 bg-white"
        style={{ border: `1px solid ${color}` }}
      >
        <img 
          src={logo} 
          alt={`${name} logo`}
          className="w-full h-full object-contain"
          onError={(e) => {
            // Fallback to letter if logo fails to load
            const target = e.currentTarget;
            target.style.display = 'none';
            const parent = target.parentElement;
            if (parent) {
              parent.style.backgroundColor = color + '20';
              parent.innerHTML = `<span class="text-xs font-bold" style="color: ${color}">${name[0]}</span>`;
            }
          }}
        />
      </div>
      
      <div className="flex-1 text-left">
        <div className="text-sm font-semibold text-matrix-green">{name}</div>
        <div className={`text-xs mt-1 px-2 py-0.5 rounded inline-block ${stateClasses[state]}`}>
          {state}
        </div>
      </div>
    </button>
  );
}
