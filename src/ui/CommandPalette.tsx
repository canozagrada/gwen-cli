import React from 'react';
import { Box, Text } from 'ink';
import { Command } from '../types';

interface CommandPaletteProps {
  commands: Command[];
  selectedIndex: number;
  visible: boolean;
}

/**
 * CommandPalette - Overlay showing available commands when "/" is typed
 */
export const CommandPalette = React.memo<CommandPaletteProps>(({
  commands,
  selectedIndex,
  visible,
}) => {
  if (!visible) return null;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={2}
      paddingY={1}
      marginTop={1}
    >
      <Box marginBottom={1}>
        <Text bold color="cyan">
          Available Commands
        </Text>
      </Box>
      {commands.map((cmd, index) => (
        <Box key={cmd.name} marginY={0}>
          <Text
            color={index === selectedIndex ? 'black' : 'cyan'}
            backgroundColor={index === selectedIndex ? 'cyan' : undefined}
          >
            {index === selectedIndex ? '▶ ' : '  '}
            /{cmd.name}
          </Text>
          <Text dimColor> - {cmd.description}</Text>
        </Box>
      ))}
      <Box marginTop={1}>
        <Text dimColor color="cyan">
          Use ↑↓ to navigate, Enter to select, Esc to close
        </Text>
      </Box>
    </Box>
  );
});
