"""GCP agent for status monitoring."""

from typing import Any, Dict, List
from datetime import datetime, timedelta

from .base import BaseAgent


class GCPAgent(BaseAgent):
    """
    Agent for interacting with Google Cloud Platform Status API.
    
    Monitors operational status and incidents.
    """
    
    def __init__(self):
        super().__init__("GCPAgent")
    
    async def initialize(self) -> None:
        """Initialize GCP Status API connection."""
        await super().initialize()
        self.status.add_message("Initializing GCP Status API client")
        self.status.add_message("GCP Status API client initialized")
    
    async def _execute_task(self) -> Dict[str, Any]:
        """
        Execute GCP status monitoring tasks.
        
        Returns:
            Dictionary containing GCP incident information
        """
        self.status.add_message("Checking GCP operational status")
        
        # Get all incidents
        all_incidents = await self._get_all_incidents()
        
        # Initialize result dictionary
        result = {
            "current_incidents": [],
            "recent_incidents": []
        }
        
        # Separate current vs recent incidents
        from datetime import timezone
        
        for incident in all_incidents:
            # Check if incident has ended
            if incident.get("end"):
                result["recent_incidents"].append(incident)
            else:
                result["current_incidents"].append(incident)
        
        if len(result["current_incidents"]) > 0:
            self.status.add_message(f"Found {len(result['current_incidents'])} current incident(s)")
        else:
            self.status.add_message("All systems operational")
        
        # Filter recent incidents to last 14 days
        self.status.add_message("Filtering incidents from the last 14 days")
        recent_incidents = await self._get_recent_incidents(all_incidents, days=14)
        result["recent_incidents"] = recent_incidents
        self.status.add_message(f"Found {len(recent_incidents)} incident(s) in the last 14 days")
        
        return result
    
    async def _get_all_incidents(self) -> List[Dict[str, Any]]:
        """Fetch all incidents from GCP Status API."""
        import aiohttp
        
        url = "https://status.cloud.google.com/incidents.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        incidents = await response.json()
                        
                        # Extract key information from incidents
                        return [
                            {
                                "id": incident.get("id", ""),
                                "number": incident.get("number", ""),
                                "begin": incident.get("begin", ""),
                                "end": incident.get("end"),
                                "external_desc": incident.get("external_desc", ""),
                                "service_name": incident.get("service_name", ""),
                                "severity": incident.get("severity", ""),
                                "status_impact": incident.get("status_impact", ""),
                                "affected_products": [
                                    p.get("title", "") for p in incident.get("affected_products", [])
                                ],
                                "uri": incident.get("uri", ""),
                                "updates_count": len(incident.get("updates", []))
                            }
                            for incident in incidents
                        ]
                    else:
                        self.logger.error(f"Failed to fetch incidents: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching incidents: {e}")
            return []
    
    async def _get_recent_incidents(self, incidents: List[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
        """Filter incidents from the last N days."""
        from datetime import timezone
        
        try:
            # Calculate cutoff date (timezone-aware)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Filter incidents from the last N days
            recent_incidents = []
            for incident in incidents:
                if incident.get("begin"):
                    try:
                        # Parse ISO 8601 date
                        begin_date = datetime.fromisoformat(incident["begin"].replace("Z", "+00:00"))
                        
                        if begin_date >= cutoff_date:
                            recent_incidents.append(incident)
                    except (ValueError, TypeError) as e:
                        self.logger.error(f"Error parsing incident date: {e}")
            
            return recent_incidents
        except Exception as e:
            self.logger.error(f"Error filtering recent incidents: {e}")
            return []
