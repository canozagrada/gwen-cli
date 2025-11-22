import React from 'react';
import { Box, Text } from 'ink';

export interface DashboardAgent {
  name: string;
  status: string;
  summary: string;
  current_incidents?: number;
  recent_incidents?: number;
  isExecuting?: boolean;
}

interface DashboardTableProps {
  agents: DashboardAgent[];
}

/**
 * DashboardTable - Compact table view showing agent status at a glance
 */
export const DashboardTable = React.memo<DashboardTableProps>(({ agents }) => {
  const getStatusColor = (status: string) => {
    const s = status.toLowerCase();
    if (s.includes('operational') || s.includes('completed') || s.includes('success')) return 'green';
    if (s.includes('degraded') || s.includes('warning')) return 'yellow';
    if (s.includes('error') || s.includes('failed') || s.includes('outage')) return 'red';
    if (s.includes('executing') || s.includes('running')) return 'cyan';
    if (s.includes('idle') || s.includes('pending')) return 'gray';
    return 'white';
  };

  const getStatusIcon = (status: string) => {
    const s = status.toLowerCase();
    if (s.includes('operational') || s.includes('completed') || s.includes('success')) return '✓';
    if (s.includes('degraded') || s.includes('warning')) return '⚠';
    if (s.includes('error') || s.includes('failed') || s.includes('outage')) return '✖';
    if (s.includes('executing') || s.includes('running')) return '⟳';
    if (s.includes('idle') || s.includes('pending')) return '○';
    return '•';
  };

  // Truncate long text to fit in table
  const truncate = (text: string, maxLength: number) => {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength - 3) + '...';
  };

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="magenta"
      paddingX={1}
      paddingY={0}
    >
      {/* Header */}
      <Box marginBottom={0}>
        <Text bold color="magenta">DASHBOARD</Text>
        <Text dimColor> - Live Agent Status</Text>
      </Box>

      {/* Table Header */}
      <Box marginTop={0}>
        <Box width={22}>
          <Text bold dimColor>Agent</Text>
        </Box>
        <Box width={18}>
          <Text bold dimColor>Status</Text>
        </Box>
        <Box width={55}>
          <Text bold dimColor>Summary</Text>
        </Box>
      </Box>

      {/* Divider */}
      <Box>
        <Text dimColor>{'─'.repeat(95)}</Text>
      </Box>

      {/* Table Rows */}
      {agents.length === 0 ? (
        <Box paddingY={1}>
          <Text dimColor>No agents running. Use /run-agent --auto to start.</Text>
        </Box>
      ) : (
        agents.map((agent, index) => (
          <Box key={index}>
            <Box width={22}>
              <Text color="cyan">{truncate(agent.name, 20)}</Text>
            </Box>
            <Box width={18}>
              <Text color={getStatusColor(agent.status)}>
                {getStatusIcon(agent.status)} {truncate(agent.status, 15)}
              </Text>
            </Box>
            <Box width={55}>
              <Text>{truncate(agent.summary, 53)}</Text>
            </Box>
          </Box>
        ))
      )}
    </Box>
  );
});
