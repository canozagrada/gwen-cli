import React from 'react';
import { Box, Text } from 'ink';

/**
 * Header component - TRON-styled header with neon cyan aesthetic
 */
export const Header = React.memo(() => {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box borderStyle="round" borderColor="cyan" paddingX={2}>
        <Text bold color="cyan">
          ◢◤ GWEN SYSTEM ONLINE ◥◣
        </Text>
      </Box>
      <Box marginTop={0}>
        <Text dimColor color="cyan">
          Multi-Agent Orchestration Interface · Type / for commands
        </Text>
      </Box>
    </Box>
  );
});
