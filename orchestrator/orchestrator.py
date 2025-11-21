"""Orchestrator implementation for coordinating multi-agent execution."""

import asyncio
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from agents import (
    CloudflareAgent,
    AzureAgent,
    AtlassianAgent,
    GitHubAgent,
    DatadogAgent,
    AWSAgent,
    GCPAgent
)
from common import (
    AgentStatus,
    AgentState,
    AgentSummary,
    get_logger,
    get_settings
)
from common.models import OrchestratorReport


class Orchestrator:
    """
    Orchestrator for coordinating multiple agent executions.
    
    Manages concurrent agent execution, state aggregation,
    and report generation with dashboard-ready output.
    """
    
    def __init__(self):
        """Initialize the orchestrator with all primary agents."""
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        
        # Initialize all primary agents
        self.agents = {
            "CloudflareAgent": CloudflareAgent(),
            "AzureAgent": AzureAgent(),
            "AtlassianAgent": AtlassianAgent(),
            "GitHubAgent": GitHubAgent(),
            "DatadogAgent": DatadogAgent(),
            "AWSAgent": AWSAgent(),
            "GCPAgent": GCPAgent()
        }
        
        # In-memory state storage for dashboard
        self.current_statuses: Dict[str, AgentStatus] = {}
        self.execution_history: List[OrchestratorReport] = []
        self.is_running = False
        self.current_execution_id: Optional[str] = None
        
        self.logger.info(f"Orchestrator initialized with {len(self.agents)} agents")
    
    async def execute_all_agents(self) -> OrchestratorReport:
        """
        Execute all agents concurrently and generate report.
        
        Returns:
            OrchestratorReport with aggregated results
        """
        if self.is_running:
            raise RuntimeError("Orchestrator is already running")
        
        self.is_running = True
        self.current_execution_id = str(uuid.uuid4())
        report = OrchestratorReport(
            execution_id=self.current_execution_id,
            start_time=datetime.now()
        )
        
        self.logger.info(f"Starting orchestrator execution: {self.current_execution_id}")
        
        try:
            # Create tasks for all agents
            tasks = []
            for agent_name, agent in self.agents.items():
                self.logger.info(f"Scheduling agent: {agent_name}")
                task = asyncio.create_task(self._execute_agent(agent_name, agent))
                tasks.append(task)
            
            # Execute all agents concurrently with semaphore for rate limiting
            # TODO: Configure max_concurrent_agents from settings
            semaphore = asyncio.Semaphore(self.settings.max_concurrent_agents)
            
            async def run_with_semaphore(task):
                async with semaphore:
                    return await task
            
            # Wait for all agents to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and generate summaries
            for agent_name, result in zip(self.agents.keys(), results):
                if isinstance(result, Exception):
                    self.logger.error(f"Agent {agent_name} failed: {result}")
                    report.errors.append(f"{agent_name}: {str(result)}")
                    # Create error status
                    error_status = AgentStatus(
                        agent_name=agent_name,
                        state=AgentState.ERROR,
                        error_message=str(result)
                    )
                    self.current_statuses[agent_name] = error_status
                elif isinstance(result, AgentStatus):
                    self.current_statuses[agent_name] = result
                    summary = await self._create_agent_summary(result)
                    report.agent_summaries.append(summary)
            
            # Determine overall status
            if report.errors:
                report.overall_status = "completed_with_errors"
            else:
                report.overall_status = "success"
            
        except Exception as e:
            self.logger.error(f"Orchestrator execution failed: {e}")
            report.overall_status = "failed"
            report.errors.append(f"Orchestrator error: {str(e)}")
            
        finally:
            report.end_time = datetime.now()
            if report.start_time and report.end_time:
                report.total_duration = (report.end_time - report.start_time).total_seconds()
            
            self.is_running = False
            self.current_execution_id = None
            
            # Store in history (keep last 10 executions)
            self.execution_history.append(report)
            if len(self.execution_history) > 10:
                self.execution_history.pop(0)
            
            self.logger.info(f"Orchestrator execution completed: {report.execution_id}")
        
        return report
    
    async def _execute_agent(self, agent_name: str, agent) -> AgentStatus:
        """
        Execute a single agent with error handling.
        
        Args:
            agent_name: Name of the agent
            agent: Agent instance
        
        Returns:
            AgentStatus with execution results
        """
        try:
            self.logger.info(f"Executing agent: {agent_name}")
            status = await agent.get_status()
            self.logger.info(f"Agent {agent_name} completed with state: {status.state}")
            return status
        except Exception as e:
            self.logger.error(f"Error executing agent {agent_name}: {e}")
            raise
    
    async def _create_agent_summary(self, status: AgentStatus) -> AgentSummary:
        """
        Create a summary from agent status.
        
        Args:
            status: AgentStatus to summarize
        
        Returns:
            AgentSummary with key metrics
        """
        # Generate summary based on agent output
        summary_text = await self.summarize_agent_output(status)
        
        # Extract key metrics from raw output
        key_metrics = {
            "status": status.state.value
        }
        
        if status.raw_output:
            # Status page monitoring agents (GitHub, Cloudflare, Azure, Atlassian, Datadog)
            if status.agent_name in ["CloudflareAgent", "AzureAgent", "AtlassianAgent", "GitHubAgent", "DatadogAgent"]:
                current_status = status.raw_output.get("status", {})
                unresolved_incidents = status.raw_output.get("unresolved_incidents", [])
                recent_incidents = status.raw_output.get("recent_incidents", [])
                scheduled_maintenance = status.raw_output.get("scheduled_maintenance", [])
                
                in_progress_maintenance = sum(1 for m in scheduled_maintenance if m.get("in_progress", False))
                
                key_metrics.update({
                    "indicator": current_status.get("indicator", "unknown"),
                    "unresolved_incidents": len(unresolved_incidents),
                    "recent_incidents_7d": len(recent_incidents),
                    "scheduled_maintenance": len(scheduled_maintenance),
                    "in_progress_maintenance": in_progress_maintenance
                })
            
            # AWS Health Dashboard
            elif status.agent_name == "AWSAgent":
                current_events = status.raw_output.get("current_events", [])
                recent_events = status.raw_output.get("recent_events", [])
                
                key_metrics.update({
                    "current_events": len(current_events),
                    "recent_events_7d": len(recent_events)
                })
            
            # GCP Status
            elif status.agent_name == "GCPAgent":
                all_incidents = status.raw_output.get("all_incidents", [])
                recent_incidents = status.raw_output.get("recent_incidents", [])
                
                # Count current incidents (those without end date)
                current_count = sum(1 for incident in all_incidents if not incident.get("end"))
                
                key_metrics.update({
                    "current_incidents": current_count,
                    "recent_incidents_7d": len(recent_incidents),
                    "total_incidents": len(all_incidents)
                })
        
        return AgentSummary(
            agent_name=status.agent_name,
            status=status.state.value,
            summary=summary_text,
            key_metrics=key_metrics,
            execution_time=status.duration_seconds()
        )
    
    async def summarize_agent_output(self, status: AgentStatus) -> str:
        """
        Generate a 1-2 sentence summary of agent output.
        
        Args:
            status: AgentStatus to summarize
        
        Returns:
            Brief summary string
        """
        if status.state == AgentState.ERROR:
            return f"Agent failed with error: {status.error_message}"
        
        if status.state == AgentState.WARNING:
            return f"Agent completed with warnings. Check logs for details."
        
        if not status.raw_output:
            return "Agent completed but returned no data."
        
        # Status page monitoring summaries
        if status.agent_name in ["CloudflareAgent", "AzureAgent", "AtlassianAgent", "GitHubAgent", "DatadogAgent"]:
            current_status = status.raw_output.get("status", {})
            unresolved_incidents = status.raw_output.get("unresolved_incidents", [])
            recent_incidents = status.raw_output.get("recent_incidents", [])
            scheduled_maintenance = status.raw_output.get("scheduled_maintenance", [])
            
            status_desc = current_status.get("description", "Unknown")
            indicator = current_status.get("indicator", "unknown")
            unresolved_count = len(unresolved_incidents)
            recent_count = len(recent_incidents)
            in_progress_maintenance = sum(1 for m in scheduled_maintenance if m.get("in_progress", False))
            
            if indicator == "none":
                if in_progress_maintenance > 0:
                    return f"Status: {status_desc}. {in_progress_maintenance} scheduled maintenance in progress."
                elif recent_count > 0:
                    return f"Status: {status_desc}. No current incidents, but {recent_count} incidents in the last 7 days."
                else:
                    return f"Status: {status_desc}. No incidents in the last 7 days."
            else:
                maintenance_note = f" {in_progress_maintenance} scheduled maintenance in progress." if in_progress_maintenance > 0 else ""
                return f"Status: {status_desc}. {unresolved_count} unresolved incident(s), {recent_count} total incidents in the last 7 days.{maintenance_note}"
        
        elif status.agent_name == "AWSAgent":
            current_events = status.raw_output.get("current_events", [])
            recent_events = status.raw_output.get("recent_events", [])
            
            current_count = len(current_events)
            recent_count = len(recent_events)
            
            if current_count > 0:
                return f"AWS Health: {current_count} current event(s), {recent_count} total events in the last 7 days."
            else:
                if recent_count > 0:
                    return f"AWS Health: No current events, but {recent_count} events in the last 7 days."
                else:
                    return "AWS Health: All services operational. No events in the last 7 days."
        
        elif status.agent_name == "GCPAgent":
            all_incidents = status.raw_output.get("all_incidents", [])
            recent_incidents = status.raw_output.get("recent_incidents", [])
            
            # Count current incidents (those without end date)
            current_count = sum(1 for incident in all_incidents if not incident.get("end"))
            recent_count = len(recent_incidents)
            
            if current_count > 0:
                return f"GCP Status: {current_count} current incident(s), {recent_count} total incidents in the last 7 days."
            else:
                if recent_count > 0:
                    return f"GCP Status: No current incidents, but {recent_count} incidents in the last 7 days."
                else:
                    return "GCP Status: All services operational. No incidents in the last 7 days."
        
        else:
            return f"Agent completed successfully with {len(status.raw_output)} data categories."
    
    def get_agent_status(self, agent_name: str) -> Optional[AgentStatus]:
        """
        Get current status for a specific agent.
        
        Args:
            agent_name: Name of the agent
        
        Returns:
            AgentStatus or None if not found
        """
        return self.current_statuses.get(agent_name)
    
    def get_all_statuses(self) -> Dict[str, AgentStatus]:
        """
        Get current status for all agents.
        
        Returns:
            Dictionary of agent names to status objects
        """
        return self.current_statuses.copy()
    
    def get_execution_history(self) -> List[OrchestratorReport]:
        """
        Get recent execution history.
        
        Returns:
            List of recent OrchestratorReport objects
        """
        return self.execution_history.copy()
    
    async def cleanup(self) -> None:
        """Cleanup all agent resources."""
        self.logger.info("Cleaning up orchestrator and all agents")
        
        cleanup_tasks = []
        for agent_name, agent in self.agents.items():
            cleanup_tasks.append(agent.cleanup())
        
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        self.logger.info("Orchestrator cleanup completed")
