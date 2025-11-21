"""
Gwen Multi-Agent System - FastAPI Application

A modular, async multi-agent orchestration system with dashboard-ready endpoints.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Dict, Any, List, Optional
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from orchestrator import Orchestrator
from common import get_logger, get_settings, AgentStatus
from common.models import OrchestratorReport

# Initialize logger and settings
logger = get_logger(__name__)
settings = get_settings()

# Global orchestrator instance
orchestrator: Optional[Orchestrator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle - startup and shutdown.
    """
    # Startup
    global orchestrator
    logger.info("Starting Gwen Multi-Agent System")
    orchestrator = Orchestrator()
    yield
    
    # Shutdown
    logger.info("Shutting down Gwen Multi-Agent System")
    if orchestrator:
        await orchestrator.cleanup()


# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent orchestration system for monitoring cloud services",
    lifespan=lifespan
)


@app.get("/")
async def root() -> Dict[str, Any]:
    """
    Root endpoint with system information.
    
    Returns:
        System status and available endpoints
    """
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "retrieve_status": "/retrieve-status",
            "agent_status": "/agent-status",
            "agent_logs": "/agent-logs/{agent_name}",
            "execution_history": "/execution-history",
            "health": "/health"
        },
        "agents": list(orchestrator.agents.keys()) if orchestrator else []
    }


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring.
    
    Returns:
        Health status of the system
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "orchestrator": {
            "is_running": orchestrator.is_running if orchestrator else False,
            "agents_count": len(orchestrator.agents) if orchestrator else 0,
            "current_execution": orchestrator.current_execution_id if orchestrator else None
        }
    }


@app.post("/retrieve-status")
async def retrieve_status(background_tasks: BackgroundTasks) -> OrchestratorReport:
    """
    Trigger orchestrator to execute all agents and retrieve current status.
    
    This endpoint runs all agents concurrently and returns an aggregated
    report with summaries and key metrics.
    
    Returns:
        OrchestratorReport with execution results
    
    Raises:
        HTTPException: If orchestrator is already running or on execution error
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    if orchestrator.is_running:
        raise HTTPException(
            status_code=409, 
            detail="Orchestrator is already running. Please wait for current execution to complete."
        )
    
    try:
        logger.info("Starting orchestrator execution via API")
        report = await orchestrator.execute_all_agents()
        
        # Log execution summary
        logger.info(f"Execution completed: {report.execution_id}")
        logger.info(f"Overall status: {report.overall_status}")
        logger.info(f"Total duration: {report.total_duration:.2f}s")
        
        return report
        
    except Exception as e:
        logger.error(f"Failed to execute orchestrator: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@app.get("/agent-status")
async def get_all_agent_status() -> Dict[str, AgentStatus]:
    """
    Get current status of all agents.
    
    Returns the in-memory status of all agents from the last execution.
    This endpoint is designed for dashboard visualization showing agent
    states, messages, and outputs.
    
    Returns:
        Dictionary mapping agent names to their current status
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    statuses = orchestrator.get_all_statuses()
    
    if not statuses:
        return {
            "message": "No agent statuses available. Run /retrieve-status first.",
            "agents": list(orchestrator.agents.keys())
        }
    
    return statuses


@app.get("/agent-status/{agent_name}")
async def get_agent_status(agent_name: str) -> AgentStatus:
    """
    Get status for a specific agent.
    
    Args:
        agent_name: Name of the agent (e.g., CloudflareAgent, AzureAgent)
    
    Returns:
        AgentStatus for the specified agent
    
    Raises:
        HTTPException: If agent not found
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    if agent_name not in orchestrator.agents:
        raise HTTPException(
            status_code=404, 
            detail=f"Agent '{agent_name}' not found. Available agents: {list(orchestrator.agents.keys())}"
        )
    
    status = orchestrator.get_agent_status(agent_name)
    
    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"No status available for agent '{agent_name}'. Run /retrieve-status first."
        )
    
    return status


@app.get("/agent-logs/{agent_name}")
async def get_agent_logs(agent_name: str) -> Dict[str, Any]:
    """
    Get detailed logs and output for a single agent.
    
    This endpoint returns comprehensive information about an agent's
    last execution including all log messages, raw output, and timing.
    
    Args:
        agent_name: Name of the agent
    
    Returns:
        Detailed agent logs and output
    
    Raises:
        HTTPException: If agent not found
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    if agent_name not in orchestrator.agents:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found. Available agents: {list(orchestrator.agents.keys())}"
        )
    
    status = orchestrator.get_agent_status(agent_name)
    
    if not status:
        return {
            "agent_name": agent_name,
            "message": "No execution data available. Run /retrieve-status first.",
            "status": "idle"
        }
    
    # Return detailed logs and output
    return {
        "agent_name": agent_name,
        "state": status.state.value,
        "execution": {
            "start_time": status.start_time.isoformat() if status.start_time else None,
            "end_time": status.end_time.isoformat() if status.end_time else None,
            "duration_seconds": status.duration_seconds()
        },
        "messages": status.messages,
        "message_count": len(status.messages),
        "raw_output": status.raw_output,
        "error": status.error_message if status.error_message else None,
        "dashboard_display": {
            "color": _get_status_color(status.state.value),
            "icon": _get_status_icon(status.state.value),
            "last_message": status.messages[-1] if status.messages else None
        }
    }


@app.get("/execution-history")
async def get_execution_history(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent execution history.
    
    Args:
        limit: Maximum number of executions to return (default: 10)
    
    Returns:
        List of recent execution reports
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    history = orchestrator.get_execution_history()
    
    # Convert to simplified format for dashboard
    simplified_history = []
    for report in history[-limit:]:
        simplified_history.append({
            "execution_id": report.execution_id,
            "start_time": report.start_time.isoformat(),
            "end_time": report.end_time.isoformat() if report.end_time else None,
            "duration_seconds": report.total_duration,
            "overall_status": report.overall_status,
            "agent_count": len(report.agent_summaries),
            "error_count": len(report.errors),
            "summary": {
                agent.agent_name: {
                    "status": agent.status,
                    "summary": agent.summary
                }
                for agent in report.agent_summaries
            }
        })
    
    return simplified_history


@app.get("/agents")
async def list_agents() -> Dict[str, List[Dict[str, Any]]]:
    """
    List all available agents with their metadata.
    
    Returns:
        Dictionary containing list of agents with their information
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    agents_info = []
    for agent_name, agent in orchestrator.agents.items():
        status = orchestrator.get_agent_status(agent_name)
        agents_info.append({
            "name": agent_name,
            "type": agent.__class__.__name__,
            "status": status.state.value if status else "idle",
            "last_execution": status.end_time.isoformat() if status and status.end_time else None,
            "description": agent.__class__.__doc__.strip().split('\n')[0] if agent.__class__.__doc__ else None
        })
    
    return {
        "agents": agents_info,
        "total": len(agents_info)
    }


@app.post("/agents/{agent_name}/execute")
async def execute_single_agent(agent_name: str) -> AgentStatus:
    """
    Execute a single agent independently.
    
    Args:
        agent_name: Name of the agent to execute
    
    Returns:
        AgentStatus with execution results
    
    Raises:
        HTTPException: If agent not found or execution fails
    """
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    if agent_name not in orchestrator.agents:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found. Available agents: {list(orchestrator.agents.keys())}"
        )
    
    try:
        agent = orchestrator.agents[agent_name]
        logger.info(f"Executing single agent: {agent_name}")
        
        status = await agent.get_status()
        orchestrator.current_statuses[agent_name] = status
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to execute agent {agent_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


def _get_status_color(status: str) -> str:
    """Get dashboard color for status."""
    colors = {
        "idle": "gray",
        "thinking": "blue",
        "completed": "green",
        "warning": "yellow",
        "error": "red"
    }
    return colors.get(status, "gray")


def _get_status_icon(status: str) -> str:
    """Get dashboard icon for status."""
    icons = {
        "idle": "○",
        "thinking": "◑",
        "completed": "●",
        "warning": "⚠",
        "error": "✖"
    }
    return icons.get(status, "○")


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=404,
        content={"detail": "Endpoint not found", "path": str(request.url)}
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "message": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    
    # Run the application
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info"
    )
