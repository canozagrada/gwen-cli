import { useState, useEffect, useMemo } from 'react';
import { useInput, useApp, Box, Text } from 'ink';
import { Header } from './ui/Header.js';
import { Prompt } from './ui/Prompt.js';
import { CommandPalette } from './ui/CommandPalette.js';
import { DashboardTable } from './ui/DashboardTable.js';
import { LogEntry, Command, AppState, DashboardAgent } from './types.js';
import { parseCommand, shouldShowCommandPalette, filterCommands } from './core/command-parser.js';
import { createCommands } from './commands/api-handlers.js';

const App: React.FC = () => {
  const { exit } = useApp();
  
  // Application state
  const [state, setState] = useState<AppState>({
    inputValue: '',
    showCommandPalette: false,
    selectedCommandIndex: 0,
    isExecuting: false,
    currentAgent: undefined,
    scrollOffset: 0,
    viewMode: 'main',
    agentResults: [],
    selectedAgentIndex: 0,
    dashboardAgents: [],
  });

  // Prevent duplicate renders by tracking if we're already rendered
  const [isInitialized, setIsInitialized] = useState(false);

  // Helper to add logs (silent - just for backend communication feedback)
  const addLog = (_message: string, _level?: LogEntry['level'], _source?: string) => {
    // Logs are not displayed in the UI, so we don't store them
    // This is here only for API compatibility with command handlers
  };

  // Set executing state
  const setExecuting = (executing: boolean) => {
    setState(prev => ({ ...prev, isExecuting: executing }));
  };

  // Set current agent
  const setCurrentAgent = (agent?: string) => {
    setState(prev => ({ ...prev, currentAgent: agent }));
  };

  // Update dashboard agents
  const setDashboardAgents = (agents: DashboardAgent[]) => {
    setState(prev => ({ ...prev, dashboardAgents: agents }));
  };

  // Create command handlers (connects to FastAPI backend)
  const commands: Command[] = createCommands(addLog, setExecuting, setCurrentAgent, setDashboardAgents);

  // Filter commands based on input
  const filteredCommands = filterCommands(commands, state.inputValue);

  // Welcome message and auto-start agents
  useEffect(() => {
    if (!isInitialized) {
      addLog('GWEN System initialized - Connected to backend', 'system');
      addLog('Backend: http://localhost:8000', 'info');
      addLog('Auto-refresh: Every 5 minutes', 'info');
      addLog('Type /help for available commands', 'info');
      setIsInitialized(true);
      
      // Auto-start agents immediately
      const startAgentsCommand = commands.find(cmd => cmd.name === 'start-agents');
      if (startAgentsCommand) {
        startAgentsCommand.execute([]);
      }
      
      // Auto-refresh every 5 minutes (300000ms)
      const interval = setInterval(() => {
        if (!state.isExecuting) {
          addLog('Auto-refresh: Starting agents...', 'system');
          if (startAgentsCommand) {
            startAgentsCommand.execute([]);
          }
        }
      }, 300000);
      
      // Cleanup interval on unmount
      return () => clearInterval(interval);
    }
  }, [isInitialized, commands, state.isExecuting]);

  // Handle keyboard input
  useInput((input: string, key: any) => {
    // Ignore input during execution
    if (state.isExecuting) {
      return;
    }

    // Handle command palette navigation
    if (state.showCommandPalette) {
      if (key.upArrow) {
        setState(prev => ({
          ...prev,
          selectedCommandIndex: Math.max(0, prev.selectedCommandIndex - 1),
        }));
        return;
      }

      if (key.downArrow) {
        setState(prev => ({
          ...prev,
          selectedCommandIndex: Math.min(
            filteredCommands.length - 1,
            prev.selectedCommandIndex + 1
          ),
        }));
        return;
      }

      if (key.escape) {
        setState(prev => ({
          ...prev,
          showCommandPalette: false,
          inputValue: '',
          selectedCommandIndex: 0,
        }));
        return;
      }

      if (key.return) {
        const selectedCommand = filteredCommands[state.selectedCommandIndex];
        if (selectedCommand) {
          setState(prev => ({
            ...prev,
            inputValue: `/${selectedCommand.name} `,
            showCommandPalette: false,
            selectedCommandIndex: 0,
          }));
        }
        return;
      }
    }

    // Handle backspace
    if (key.backspace || key.delete) {
      setState(prev => {
        const newValue = prev.inputValue.slice(0, -1);
        const showPalette = shouldShowCommandPalette(newValue);
        return {
          ...prev,
          inputValue: newValue,
          showCommandPalette: showPalette,
          selectedCommandIndex: showPalette ? 0 : prev.selectedCommandIndex,
        };
      });
      return;
    }

    // Handle Enter - execute command
    if (key.return) {
      const parsed = parseCommand(state.inputValue);
      
      if (!parsed) {
        addLog('Invalid command. Type /help for available commands', 'error', 'system');
        setState(prev => ({ ...prev, inputValue: '' }));
        return;
      }

      const command = commands.find(
        cmd => cmd.name === parsed.command || cmd.aliases?.includes(parsed.command)
      );

      if (!command) {
        addLog(`Unknown command: ${parsed.command}`, 'error', 'system');
        setState(prev => ({ ...prev, inputValue: '' }));
        return;
      }

      // Clear input
      setState(prev => ({ ...prev, inputValue: '' }));

      // Execute command asynchronously
      command.execute(parsed.args).catch(error => {
        addLog(`Command error: ${error.message}`, 'error', 'system');
      });

      return;
    }

    // Handle Ctrl+C
    if (key.ctrl && input === 'c') {
      addLog('Exiting...', 'system');
      exit();
      return;
    }

    // Regular character input
    if (!key.ctrl && !key.meta && input) {
      setState(prev => {
        const newValue = prev.inputValue + input;
        const showPalette = shouldShowCommandPalette(newValue);
        return {
          ...prev,
          inputValue: newValue,
          showCommandPalette: showPalette,
          selectedCommandIndex: showPalette ? 0 : prev.selectedCommandIndex,
        };
      });
    }
  });

  return (
    <Box flexDirection="column" padding={1}>
      <Box flexDirection="column">
        <Header />
        <DashboardTable agents={state.dashboardAgents} />
        {!state.showCommandPalette && (
          <Prompt
            value={state.inputValue}
            isExecuting={state.isExecuting}
            currentAgent={state.currentAgent}
          />
        )}
      </Box>
      {state.showCommandPalette && (
        <Box flexDirection="column" marginTop={1}>
          <CommandPalette
            commands={filteredCommands}
            selectedIndex={state.selectedCommandIndex}
            visible={state.showCommandPalette}
          />
          <Box marginTop={1}>
            <Text bold color="cyan">▶ </Text>
            <Text>{state.inputValue}</Text>
            <Text color="cyan">▋</Text>
          </Box>
        </Box>
      )}
    </Box>
  );
};

export default App;
