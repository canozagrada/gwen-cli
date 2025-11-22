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
        
        # Get scheduled maintenance
        scheduled = await self._get_scheduled_maintenance()
        in_progress_count = sum(1 for m in scheduled if m.get("in_progress", False))
        
        # Initialize result dictionary
        result = {
            "status": {
                "indicator": "none",
                "description": "All Systems Operational",
                "updated_at": datetime.now().isoformat()
            },
            "ongoing_incidents": [],
            "recent_incidents": [],
            "scheduled_maintenance": scheduled
        }
        
        # Separate current vs recent incidents
        from datetime import timezone
        
        for incident in all_incidents:
            # Check if incident has ended
            if incident.get("end"):
                result["recent_incidents"].append(incident)
            else:
                result["ongoing_incidents"].append(incident)
        
        # Update status based on ongoing incidents
        if len(result["ongoing_incidents"]) > 0:
            result["status"]["indicator"] = "minor"
            result["status"]["description"] = f"{len(result['ongoing_incidents'])} active incident(s)"
            if in_progress_count > 0:
                result["status"]["description"] += f" ({in_progress_count} maintenance in progress)"
            self.status.add_message(f"Found {len(result['ongoing_incidents'])} current incident(s)")
        else:
            if in_progress_count > 0:
                result["status"]["description"] = f"All Systems Operational ({in_progress_count} maintenance in progress)"
            self.status.add_message("All systems operational")
        
        # Filter recent incidents to last 14 days
        self.status.add_message("Filtering incidents from the last 14 days")
        recent_incidents = await self._get_recent_incidents(all_incidents, days=14)
        result["recent_incidents"] = recent_incidents
        self.status.add_message(f"Found {len(recent_incidents)} incident(s) in the last 14 days")
        
        if scheduled:
            self.status.add_message(f"Found {len(scheduled)} upcoming scheduled maintenance window(s)")
        
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
    
    async def _get_scheduled_maintenance(self) -> List[Dict[str, Any]]:
        """
        Fetch scheduled maintenance from GCP.
        
        Note: GCP doesn't have a separate scheduled maintenance endpoint.
        Maintenance is included in the incidents feed with a special flag.
        """
        import aiohttp
        from datetime import timezone
        
        url = "https://status.cloud.google.com/incidents.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        incidents = await response.json()
                        now = datetime.now(timezone.utc)
                        
                        # Filter for maintenance-type incidents that are future or in-progress
                        maintenance = []
                        for incident in incidents:
                            # Check if it's a maintenance event (GCP uses specific keywords)
                            external_desc = incident.get("external_desc", "").lower()
                            service_name = incident.get("service_name", "").lower()
                            
                            is_maintenance = any(kw in external_desc or kw in service_name 
                                               for kw in ["maintenance", "scheduled", "planned"])
                            
                            if is_maintenance and incident.get("begin"):
                                try:
                                    begin_date = datetime.fromisoformat(incident["begin"].replace("Z", "+00:00"))
                                    
                                    # Check if maintenance is in the future or ongoing
                                    if incident.get("end"):
                                        end_date = datetime.fromisoformat(incident["end"].replace("Z", "+00:00"))
                                        # Include if not yet ended
                                        if end_date >= now:
                                            in_progress = begin_date <= now <= end_date
                                            maintenance.append({
                                                "id": incident.get("id", ""),
                                                "number": incident.get("number", ""),
                                                "name": incident.get("external_desc", ""),
                                                "scheduled_for": incident["begin"],
                                                "scheduled_until": incident["end"],
                                                "in_progress": in_progress,
                                                "affected_products": [
                                                    p.get("title", "") for p in incident.get("affected_products", [])
                                                ],
                                                "service_name": incident.get("service_name", ""),
                                                "uri": incident.get("uri", "")
                                            })
                                    else:
                                        # Future maintenance without end date
                                        if begin_date >= now:
                                            maintenance.append({
                                                "id": incident.get("id", ""),
                                                "number": incident.get("number", ""),
                                                "name": incident.get("external_desc", ""),
                                                "scheduled_for": incident["begin"],
                                                "scheduled_until": None,
                                                "in_progress": False,
                                                "affected_products": [
                                                    p.get("title", "") for p in incident.get("affected_products", [])
                                                ],
                                                "service_name": incident.get("service_name", ""),
                                                "uri": incident.get("uri", "")
                                            })
                                except (ValueError, TypeError) as e:
                                    self.logger.warning(f"Error parsing maintenance date: {e}")
                                    continue
                        
                        return maintenance
                    else:
                        self.logger.error(f"Failed to fetch maintenance: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching scheduled maintenance: {e}")
            return []
