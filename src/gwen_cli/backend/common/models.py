"""Shared data models for the multi-agent system."""

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class AgentState(str, Enum):
    """Enumeration of possible agent states."""
    IDLE = "idle"
    THINKING = "thinking"
    COMPLETED = "completed"
    WARNING = "warning"
    ERROR = "error"


class AgentStatus(BaseModel):
    """Status model for tracking individual agent state and output."""
    
    agent_name: str = Field(..., description="Name of the agent")
    state: AgentState = Field(default=AgentState.IDLE, description="Current agent state")
    start_time: Optional[datetime] = Field(None, description="Execution start time")
    end_time: Optional[datetime] = Field(None, description="Execution end time")
    messages: List[str] = Field(default_factory=list, description="Log messages from agent")
    raw_output: Optional[Dict[str, Any]] = Field(None, description="Raw output data from agent")
    error_message: Optional[str] = Field(None, description="Error message if state is ERROR")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def add_message(self, message: str) -> None:
        """Add a log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages.append(f"[{timestamp}] {message}")
    
    def duration_seconds(self) -> Optional[float]:
        """Calculate execution duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class AgentSummary(BaseModel):
    """Summary model for aggregated agent outputs."""
    
    agent_name: str = Field(..., description="Name of the agent")
    status: str = Field(..., description="Current status")
    summary: str = Field(..., description="Brief summary of agent output")
    key_metrics: Dict[str, Any] = Field(default_factory=dict, description="Key metrics extracted")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    raw_output: Optional[Dict[str, Any]] = Field(None, description="Raw output data from agent")
    start_time: Optional[datetime] = Field(None, description="Execution start time")
    end_time: Optional[datetime] = Field(None, description="Execution end time")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class OrchestratorReport(BaseModel):
    """Complete report from orchestrator execution."""
    
    execution_id: str = Field(..., description="Unique execution ID")
    start_time: datetime = Field(..., description="Report generation start time")
    end_time: Optional[datetime] = Field(None, description="Report generation end time")
    total_duration: Optional[float] = Field(None, description="Total execution time in seconds")
    agent_summaries: List[AgentSummary] = Field(default_factory=list, description="All agent summaries")
    overall_status: str = Field(default="pending", description="Overall execution status")
    errors: List[str] = Field(default_factory=list, description="List of any errors encountered")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
