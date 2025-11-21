import { useState, useEffect } from 'react';
import AgentList from './components/AgentList';
import DashboardView from './components/DashboardView';
import AgentDetailView from './components/AgentDetailView';
import AgentLogs from './components/AgentLogs';
import { getAgentStatuses, getAgentLogs } from './api';
import type { AgentStatus, AgentLogs as AgentLogsType, OrchestratorReport, AgentSummary } from './types';

function App() {
  const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>({});
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentLogs, setAgentLogs] = useState<AgentLogsType | null>(null);
  const [report, setReport] = useState<OrchestratorReport | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [isRunningReport, setIsRunningReport] = useState(false);
  const [autoRun, setAutoRun] = useState(false);

  // Poll agent statuses every 3 seconds
  useEffect(() => {
    const fetchStatuses = async () => {
      try {
        const statuses = await getAgentStatuses();
        setAgentStatuses(statuses);
        
        // Build report from current statuses if we have any data
        if (Object.keys(statuses).length > 0) {
          const summaries: AgentSummary[] = Object.entries(statuses).map(([name, status]) => ({
            agent_name: name,
            status: status.state === 'completed' ? 'operational' : status.state,
            summary: status.messages[status.messages.length - 1] || 'No summary available',
            key_metrics: status.raw_output || {},
            execution_time: status.end_time && status.start_time 
              ? (new Date(status.end_time).getTime() - new Date(status.start_time).getTime()) / 1000
              : 0,
          }));
          
          setReport({
            execution_id: `exec-${Date.now()}`,
            start_time: new Date().toISOString(),
            end_time: new Date().toISOString(),
            total_duration: 0,
            agent_summaries: summaries,
            overall_status: Object.values(statuses).every(s => s.state === 'completed') ? 'success' : 'running',
            errors: Object.values(statuses)
              .filter(s => s.error_message)
              .map(s => s.error_message || ''),
          });
        }
      } catch (error) {
        console.error('Failed to fetch agent statuses:', error);
      }
    };

    fetchStatuses();
    const interval = setInterval(fetchStatuses, 3000);
    return () => clearInterval(interval);
  }, []);

  // Fetch logs when agent selected
  useEffect(() => {
    if (!selectedAgent) {
      setAgentLogs(null);
      return;
    }

    const fetchLogs = async () => {
      setLogsLoading(true);
      try {
        const logs = await getAgentLogs(selectedAgent);
        setAgentLogs(logs);
      } catch (error) {
        console.error('Failed to fetch agent logs:', error);
      } finally {
        setLogsLoading(false);
      }
    };

    fetchLogs();
    const interval = setInterval(fetchLogs, 3000);
    return () => clearInterval(interval);
  }, [selectedAgent]);

  const selectedStatus = selectedAgent ? agentStatuses[selectedAgent] : null;
  const selectedSummary = selectedAgent 
    ? report?.agent_summaries.find(s => s.agent_name === selectedAgent) || null
    : null;

  const handleRunReport = async () => {
    setIsRunningReport(true);
    try {
      // Trigger backend status retrieval
      // This will cause all agents to execute
      await fetch('/api/retrieve-status', { method: 'POST' });
      // Status polling will pick up the changes automatically
    } catch (error) {
      console.error('Failed to retrieve status:', error);
    } finally {
      setIsRunningReport(false);
    }
  };

  // Auto-run reports every 5 minutes when enabled
  useEffect(() => {
    if (!autoRun) return;

    // Run immediately when auto-run is enabled
    handleRunReport();

    // Then run every 5 minutes (300000ms)
    const interval = setInterval(handleRunReport, 300000);
    return () => clearInterval(interval);
  }, [autoRun]);

  return (
    <div className="h-screen w-screen bg-matrix-darker text-matrix-green font-mono overflow-hidden flex">
      {/* Left Panel - Agent List */}
      <div className="w-80 h-full border-r border-matrix-green/30 flex-shrink-0">
        <AgentList
          agentStatuses={agentStatuses}
          selectedAgent={selectedAgent}
          onSelectAgent={(agentId) => setSelectedAgent(agentId === selectedAgent ? null : agentId)}
          onRunReport={handleRunReport}
          autoRun={autoRun}
          onToggleAutoRun={() => setAutoRun(!autoRun)}
        />
      </div>

      {/* Center Panel - Dashboard or Agent Detail */}
      <div className="flex-1 h-full overflow-hidden">
        {selectedAgent ? (
          <AgentDetailView
            agentId={selectedAgent}
            status={selectedStatus}
            summary={selectedSummary}
          />
        ) : (
          <DashboardView report={report} isLoading={false} />
        )}
      </div>

      {/* Right Panel - Logs */}
      <div className="w-96 h-full border-l border-matrix-green/30 flex-shrink-0">
        <AgentLogs logs={agentLogs} isLoading={logsLoading} />
      </div>
    </div>
  );
}

export default App;
