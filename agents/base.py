"""Base agent implementation with common functionality."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime
import asyncio
import random

from common import AgentStatus, AgentState, get_logger


class BaseAgent(ABC):
    """
    Abstract base class for all primary agents.
    
    Provides common functionality for status tracking, logging,
    and async execution patterns.
    """
    
    def __init__(self, name: str):
        """
        Initialize base agent.
        
        Args:
            name: Agent identifier name
        """
        self.name = name
        self.logger = get_logger(f"agent.{name}")
        self.status = AgentStatus(agent_name=name)
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize agent resources and connections.
        
        Override this method to set up API clients, connections, etc.
        """
        self.logger.info(f"Initializing {self.name}")
        self._initialized = True
        self.status.add_message(f"Agent {self.name} initialized")
    
    async def cleanup(self) -> None:
        """
        Cleanup agent resources.
        
        Override this method to close connections, cleanup resources, etc.
        """
        self.logger.info(f"Cleaning up {self.name}")
        self.status.add_message(f"Agent {self.name} cleaned up")
    
    @abstractmethod
    async def _execute_task(self) -> Dict[str, Any]:
        """
        Execute the agent's primary task.
        
        This method should be implemented by each specific agent
        to perform their unique operations.
        
        Returns:
            Dictionary containing task results
        """
        pass
    
    async def get_status(self) -> AgentStatus:
        """
        Execute agent task and return current status.
        
        Returns:
            AgentStatus object with execution results
        """
        try:
            # Set status to thinking
            self.status.state = AgentState.THINKING
            self.status.start_time = datetime.now()
            self.status.add_message(f"Starting execution for {self.name}")
            self.logger.info(f"Agent {self.name} starting execution")
            
            # Initialize if needed
            if not self._initialized:
                await self.initialize()
            
            # Execute the actual task with timeout
            # TODO: Make timeout configurable via settings
            result = await asyncio.wait_for(
                self._execute_task(),
                timeout=30.0
            )
            
            # Update status with results
            self.status.raw_output = result
            self.status.state = AgentState.COMPLETED
            self.status.add_message(f"Execution completed successfully for {self.name}")
            self.logger.info(f"Agent {self.name} completed successfully")
            
        except asyncio.TimeoutError:
            self.status.state = AgentState.WARNING
            self.status.error_message = "Task execution timed out"
            self.status.add_message(f"Timeout occurred for {self.name}")
            self.logger.warning(f"Agent {self.name} timed out")
            
        except Exception as e:
            self.status.state = AgentState.ERROR
            self.status.error_message = str(e)
            self.status.add_message(f"Error occurred: {str(e)}")
            self.logger.error(f"Agent {self.name} encountered error: {e}")
        
        finally:
            self.status.end_time = datetime.now()
            
        return self.status
    
    async def simulate_api_call(self, duration: float = None) -> Dict[str, Any]:
        """
        Simulate an API call with configurable delay.
        
        Args:
            duration: Simulated call duration in seconds
        
        Returns:
            Placeholder response data
        """
        if duration is None:
            duration = random.uniform(0.5, 2.0)
        
        await asyncio.sleep(duration)
        return {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "simulated": True
        }
