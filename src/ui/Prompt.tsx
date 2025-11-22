import React from 'react';
import { Box, Text } from 'ink';

interface PromptProps {
  value: string;
  isExecuting: boolean;
  currentAgent?: string;
}

/**
 * Prompt - Command input prompt with TRON styling
 */
export const Prompt = React.memo<PromptProps>(({ value, isExecuting, currentAgent }) => {
  const getPromptSymbol = () => {
    if (isExecuting) return '◉';
    return '▶';
  };

  const getPromptColor = () => {
    if (isExecuting) return 'yellow';
    return 'cyan';
  };

  return (
    <Box marginTop={1}>
      <Text bold color={getPromptColor()}>
        {getPromptSymbol()}{' '}
      </Text>
      {currentAgent && (
        <Text color="magenta">[{currentAgent}] </Text>
      )}
      <Text>{value}</Text>
      <Text color="cyan">▋</Text>
    </Box>
  );
});
