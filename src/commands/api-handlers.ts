import { Command, LogEntry, AgentResult, DashboardAgent } from '../types.js';
import { apiClient } from '../core/api-client.js';

/**
 * Create all command handlers for the application
 * These handlers connect to the FastAPI backend
 */
export function createCommands(
  addLog: (message: string, level?: LogEntry['level'], source?: string) => void,
  setExecuting: (executing: boolean) => void,
  setCurrentAgent: (agent?: string) => void,
  setDashboardAgents?: (agents: DashboardAgent[]) => void
): Command[] {

  // Helper function to execute all agents
  const executeAllAgents = async () => {
    addLog('Starting all agents...', 'system');
    setExecuting(true);
    setCurrentAgent('All Agents');

    const report = await apiClient.retrieveStatus();
    
    addLog(`Execution ID: ${report.execution_id}`, 'info', 'system');
    addLog(`Overall Status: ${report.overall_status}`, 
      report.overall_status === 'success' ? 'success' : 'warn', 'system');
    if (report.total_duration !== undefined && report.total_duration !== null) {
      addLog(`Total Time: ${report.total_duration.toFixed(2)}s`, 'info', 'system');
    }
    
    // Update dashboard with agent statuses
    const dashboardAgents: DashboardAgent[] = report.agent_summaries.map(agent => {
      // Extract incident counts from key_metrics if available
      let summary = agent.summary || 'No summary available';
      
      // Determine actual service health status from indicator
      let serviceStatus = 'Unknown';
      if (agent.key_metrics) {
        const indicator = agent.key_metrics.indicator;
        const currentIncidents = agent.key_metrics.current_incidents || 
                               agent.key_metrics.current_events || 
                               agent.key_metrics.unresolved_incidents || 0;
        const recentIncidents = agent.key_metrics.recent_incidents_7d || 
                              agent.key_metrics.recent_events_7d || 0;
        
        // Map indicator to user-friendly status
        if (indicator === 'none') {
          serviceStatus = 'Operational';
        } else if (indicator === 'minor') {
          serviceStatus = 'Degraded';
        } else if (indicator === 'major') {
          serviceStatus = 'Major Outage';
        } else if (indicator === 'critical') {
          serviceStatus = 'Critical Outage';
        } else if (agent.key_metrics.status === 'completed') {
          // For agents without indicator (AWS, GCP), check incidents
          if (currentIncidents > 0) {
            serviceStatus = 'Issues Detected';
          } else {
            serviceStatus = 'Operational';
          }
        }
        
        // Build a more informative summary
        if (currentIncidents > 0) {
          summary = `${currentIncidents} active incident${currentIncidents > 1 ? 's' : ''}`;
        } else if (recentIncidents > 0) {
          summary = `${recentIncidents} incident${recentIncidents > 1 ? 's' : ''} over last 7 days`;
        } else {
          summary = 'No incidents over last 7 days';
        }
      }
      
      return {
        name: agent.agent_name,
        status: serviceStatus,
        summary,
        isExecuting: false,
      };
    });

    if (setDashboardAgents) {
      setDashboardAgents(dashboardAgents);
    }
    
    // Log each agent's result
    for (const agent of report.agent_summaries) {
      addLog(`${agent.agent_name}: ${agent.status}`, 'info', agent.agent_name);
      
      if (agent.summary) {
        addLog(`  ${agent.summary}`, 'info', agent.agent_name);
      }
      
      if (agent.execution_time !== undefined && agent.execution_time !== null) {
        addLog(`  Time: ${agent.execution_time.toFixed(2)}s`, 'info', agent.agent_name);
      }
      
      // Display key metrics if available
      if (agent.key_metrics && Object.keys(agent.key_metrics).length > 0) {
        addLog(`  Metrics:`, 'info', agent.agent_name);
        Object.entries(agent.key_metrics).forEach(([key, value]) => {
          addLog(`    ${key}: ${JSON.stringify(value)}`, 'info', agent.agent_name);
        });
      }
    }

    // Log any overall errors
    if (report.errors && report.errors.length > 0) {
      addLog('Errors encountered:', 'warn', 'system');
      report.errors.forEach(err => {
        addLog(`  ${err}`, 'error', 'system');
      });
    }

    setExecuting(false);
    setCurrentAgent(undefined);
    addLog('All agents completed', 'success', 'system');
  };
  return [
    {
      name: 'start-agents',
      description: 'Execute all agents',
      aliases: ['start', 'run'],
      execute: async () => {
        try {
          await executeAllAgents();
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : String(error);
          addLog(`Failed to execute agents: ${errorMessage}`, 'error', 'system');
          setExecuting(false);
          setCurrentAgent(undefined);
        }
      },
    },
    {
      name: 'run-agent',
      description: 'Execute a specific agent',
      execute: async (args: string[]) => {
        if (args.length === 0) {
          addLog('Usage: /run-agent <agent-name>', 'error', 'system');
          return;
        }

        try {
          const agentName = args[0];
          addLog(`Executing agent: ${agentName}`, 'system');
          setCurrentAgent(agentName);
          setExecuting(true);

          const result = await apiClient.executeAgent(agentName);
          
          const level = result.state === 'completed' ? 'success' : 
                       result.state === 'error' ? 'error' : 'warn';
          addLog(`State: ${result.state}`, level, agentName);
          
          // Note: single agent execution might not return execution_time
          
          if (result.error_message) {
            addLog(`Error: ${result.error_message}`, 'error', agentName);
          }

          // Fetch and display logs
          try {
            const logs = await apiClient.getAgentLogs(agentName);
            
            // Backend returns AgentStatus with 'messages' array
            const logMessages = logs.messages || [];
            
            if (logMessages && logMessages.length > 0) {
              addLog('Agent messages:', 'info', agentName);
              logMessages.forEach(log => {
                addLog(log, 'info', agentName);
              });
            }
            
            // Display raw output if available
            if ((logs as any).raw_output) {
              addLog('Raw output available', 'info', agentName);
            }
          } catch (error) {
            // Logs might not be available yet
          }

          setExecuting(false);
          setCurrentAgent(undefined);
          addLog(`Agent ${agentName} execution complete`, 'success', 'system');

        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : String(error);
          addLog(`Failed to execute agent: ${errorMessage}`, 'error', 'system');
          setExecuting(false);
          setCurrentAgent(undefined);
        }
      },
    },
    {
      name: 'list-agents',
      description: 'List all available agents from backend',
      aliases: ['ls', 'agents'],
      execute: async () => {
        try {
          addLog('Fetching agents from backend...', 'system');
          
          const info = await apiClient.getSystemInfo();
          
          if (!info.agents || info.agents.length === 0) {
            addLog('No agents found', 'warn', 'system');
            return;
          }

          addLog(`Found ${info.agents.length} agent(s)`, 'success', 'system');

          // Try to get current status and populate dashboard
          try {
            const statuses = await apiClient.getAgentStatus();
            
            const dashboardAgents: DashboardAgent[] = info.agents.map(agentName => {
              const status = statuses[agentName];
              
              if (status) {
                // Map agent state to display status
                let displayStatus = 'Idle';
                if (status.state === 'completed') displayStatus = 'Ready';
                else if (status.state === 'error') displayStatus = 'Error';
                else if (status.state === 'thinking') displayStatus = 'Running';
                else if (status.state === 'warning') displayStatus = 'Warning';
                
                // Simple summary based on state
                let summary = 'No recent activity';
                if (status.state === 'completed') {
                  summary = 'Ready';
                } else if (status.state === 'error') {
                  summary = 'Execution failed';
                } else if (status.state === 'thinking') {
                  summary = 'Executing...';
                } else if (status.state === 'warning') {
                  summary = 'Completed with warnings';
                }
                
                return {
                  name: agentName,
                  status: displayStatus,
                  summary,
                  isExecuting: false,
                };
              } else {
                return {
                  name: agentName,
                  status: 'Idle',
                  summary: 'Not yet executed',
                  isExecuting: false,
                };
              }
            });
            
            if (setDashboardAgents) {
              setDashboardAgents(dashboardAgents);
            }
            
            addLog('Agent list displayed in dashboard', 'success', 'system');
          } catch (error) {
            // Status not available, show basic list
            const dashboardAgents: DashboardAgent[] = info.agents.map(agentName => ({
              name: agentName,
              status: 'Unknown',
              summary: 'Status not available',
              isExecuting: false,
            }));
            
            if (setDashboardAgents) {
              setDashboardAgents(dashboardAgents);
            }
            
            addLog('Agent list displayed (status unavailable)', 'warn', 'system');
          }

        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : String(error);
          addLog(`Failed to list agents: ${errorMessage}`, 'error', 'system');
          addLog('Make sure the backend is running on http://localhost:8000', 'warn', 'system');
        }
      },
    },
    {
      name: 'help',
      description: 'Show help information',
      aliases: ['?', 'h'],
      execute: async () => {
        addLog('GWEN Command Reference', 'system');
        addLog('Connected to FastAPI backend at http://localhost:8000', 'info', 'system');
        addLog('Auto-refresh: Every 5 minutes', 'info', 'system');
        addLog('', 'info');
        addLog('/start-agents      - Execute all agents', 'info');
        addLog('/run-agent <name>  - Execute a specific agent', 'info');
        addLog('/list-agents       - List all available agents', 'info');
        addLog('/help              - Show this help', 'info');
        addLog('/exit              - Exit GWEN', 'info');
        addLog('', 'info');
        addLog('Press / to open command palette', 'system');
      },
    },
    {
      name: 'exit',
      description: 'Exit GWEN',
      aliases: ['quit', 'q'],
      execute: async () => {
        addLog('Shutting down GWEN...', 'system');
        process.exit(0);
      },
    },
  ];
}
