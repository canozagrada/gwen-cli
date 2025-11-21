"""Cloudflare agent for status monitoring."""

from typing import Any, Dict, List
from datetime import datetime, timedelta

from .base import BaseAgent


class CloudflareAgent(BaseAgent):
    """
    Agent for interacting with Cloudflare Status API.
    
    Monitors operational status and incidents.
    """
    
    def __init__(self):
        super().__init__("CloudflareAgent")
    
    async def initialize(self) -> None:
        """Initialize Cloudflare Status API connection."""
        await super().initialize()
        self.status.add_message("Initializing Cloudflare Status API client")
        self.status.add_message("Cloudflare Status API client initialized")
    
    async def _execute_task(self) -> Dict[str, Any]:
        """
        Execute Cloudflare status monitoring tasks.
        
        Returns:
            Dictionary containing Cloudflare status and incident information
        """
        self.status.add_message("Checking Cloudflare operational status")
        
        # Check current status
        status_data = await self._get_cloudflare_status()
        
        # Check for scheduled maintenance
        scheduled = await self._get_scheduled_maintenance()
        in_progress_count = sum(1 for m in scheduled if m.get("in_progress", False))
        
        # Update status description if maintenance is happening
        original_status = status_data['description']
        if in_progress_count > 0:
            status_data['description'] = f"{original_status} ({in_progress_count} scheduled maintenance in progress)"
            self.status.add_message(f"Status: {status_data['description']}")
        else:
            self.status.add_message(f"Status: {original_status}")
        
        # Initialize result dictionary
        result = {
            "status": status_data,
            "unresolved_incidents": [],
            "recent_incidents": [],
            "scheduled_maintenance": scheduled
        }
        
        # If not operational, get unresolved incidents
        if status_data['indicator'] != "none":
            self.status.add_message("System not operational - fetching unresolved incidents")
            unresolved = await self._get_unresolved_incidents()
            result["unresolved_incidents"] = unresolved
            self.status.add_message(f"Found {len(unresolved)} unresolved incident(s)")
        else:
            self.status.add_message("All systems operational")
        
        # Get incidents from the last 14 days
        self.status.add_message("Fetching incidents from the last 14 days")
        recent_incidents = await self._get_recent_incidents(days=14)
        result["recent_incidents"] = recent_incidents
        self.status.add_message(f"Found {len(recent_incidents)} incident(s) in the last 14 days")
        
        if scheduled:
            self.status.add_message(f"Found {len(scheduled)} upcoming scheduled maintenance window(s)")
        
        return result
    
    async def _get_cloudflare_status(self) -> Dict[str, Any]:
        """Fetch current Cloudflare operational status."""
        import aiohttp
        
        url = "https://www.cloudflarestatus.com/api/v2/status.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "indicator": data["status"]["indicator"],
                            "description": data["status"]["description"],
                            "updated_at": data["page"]["updated_at"]
                        }
                    else:
                        self.logger.error(f"Failed to fetch Cloudflare status: {response.status}")
                        return {
                            "indicator": "unknown",
                            "description": "Unable to fetch status",
                            "updated_at": datetime.now().isoformat()
                        }
        except Exception as e:
            self.logger.error(f"Error fetching Cloudflare status: {e}")
            return {
                "indicator": "error",
                "description": f"Error: {str(e)}",
                "updated_at": datetime.now().isoformat()
            }
    
    async def _get_unresolved_incidents(self) -> List[Dict[str, Any]]:
        """Fetch unresolved incidents from Cloudflare Status API."""
        import aiohttp
        
        url = "https://www.cloudflarestatus.com/api/v2/incidents/unresolved.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        incidents = data.get("incidents", [])
                        
                        # Extract key information from incidents
                        return [
                            {
                                "id": incident["id"],
                                "name": incident["name"],
                                "status": incident["status"],
                                "impact": incident["impact"],
                                "created_at": incident["created_at"],
                                "updated_at": incident["updated_at"],
                                "shortlink": incident.get("shortlink", ""),
                                "components": [c["name"] for c in incident.get("components", [])]
                            }
                            for incident in incidents
                        ]
                    else:
                        self.logger.error(f"Failed to fetch unresolved incidents: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching unresolved incidents: {e}")
            return []
    
    async def _get_recent_incidents(self, days: int = 7) -> List[Dict[str, Any]]:
        """Fetch incidents from the last N days."""
        import aiohttp
        from datetime import timezone
        
        url = "https://www.cloudflarestatus.com/api/v2/incidents.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        incidents = data.get("incidents", [])
                        
                        # Calculate cutoff date (timezone-aware)
                        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                        
                        # Filter incidents from the last N days
                        recent_incidents = []
                        for incident in incidents:
                            created_at = datetime.fromisoformat(incident["created_at"].replace("Z", "+00:00"))
                            
                            if created_at >= cutoff_date:
                                recent_incidents.append({
                                    "id": incident["id"],
                                    "name": incident["name"],
                                    "status": incident["status"],
                                    "impact": incident["impact"],
                                    "created_at": incident["created_at"],
                                    "resolved_at": incident.get("resolved_at"),
                                    "shortlink": incident.get("shortlink", ""),
                                    "components": [c["name"] for c in incident.get("components", [])],
                                    "updates_count": len(incident.get("incident_updates", []))
                                })
                        
                        return recent_incidents
                    else:
                        self.logger.error(f"Failed to fetch incidents: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching recent incidents: {e}")
            return []
    
    async def _get_scheduled_maintenance(self) -> List[Dict[str, Any]]:
        """Fetch scheduled maintenance windows."""
        import aiohttp
        from datetime import timezone
        
        url = "https://www.cloudflarestatus.com/api/v2/scheduled-maintenances.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        maintenances = data.get("scheduled_maintenances", [])
                        now = datetime.now(timezone.utc)
                        
                        # Extract upcoming and in-progress maintenance
                        result = []
                        for maint in maintenances:
                            scheduled_for = datetime.fromisoformat(maint["scheduled_for"].replace("Z", "+00:00"))
                            scheduled_until = datetime.fromisoformat(maint["scheduled_until"].replace("Z", "+00:00"))
                            
                            # Check if maintenance is currently in progress
                            in_progress = scheduled_for <= now <= scheduled_until
                            
                            # Only include future or currently active maintenance
                            if scheduled_until >= now:
                                result.append({
                                    "id": maint["id"],
                                    "name": maint["name"],
                                    "status": maint["status"],
                                    "scheduled_for": maint["scheduled_for"],
                                    "scheduled_until": maint["scheduled_until"],
                                    "in_progress": in_progress,
                                    "impact": maint.get("impact", "maintenance"),
                                    "components": [c["name"] for c in maint.get("components", [])],
                                    "shortlink": maint.get("shortlink", "")
                                })
                        
                        return result
                    else:
                        self.logger.error(f"Failed to fetch scheduled maintenance: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching scheduled maintenance: {e}")
            return []
