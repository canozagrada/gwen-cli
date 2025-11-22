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
        
        # Get components to understand regional status
        components = await self._get_components()
        
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
        
        # Track non-operational components
        non_operational = [c for c in components if c["status"] != "operational"]
        non_operational_by_region = self._group_components_by_region(non_operational) if non_operational else {}
        
        # Log for debugging
        if non_operational:
            self.logger.info(f"Found {len(non_operational)} non-operational components")
            for comp in non_operational[:5]:  # Log first 5
                self.logger.info(f"  Component: {comp['name']} - Status: {comp['status']}")
        
        # Initialize result dictionary
        result = {
            "status": status_data,
            "ongoing_incidents": [],
            "recent_incidents": [],
            "scheduled_maintenance": scheduled,
            "components": components,
            "components_by_region": self._group_components_by_region(components),
            "non_operational_components": non_operational,
            "non_operational_components_by_region": non_operational_by_region
        }
        
        # If not operational, get unresolved incidents
        if status_data['indicator'] != "none":
            self.status.add_message("System not operational - fetching unresolved incidents")
            unresolved = await self._get_unresolved_incidents()
            result["ongoing_incidents"] = unresolved
            self.status.add_message(f"Found {len(unresolved)} unresolved incident(s)")
            
            # Group incidents by region
            result["ongoing_incidents_by_region"] = self._group_incidents_by_region(unresolved)
        else:
            self.status.add_message("All systems operational")
            if non_operational:
                self.status.add_message(f"Note: {len(non_operational)} component(s) not operational (re-routed/degraded)")
        
        # Get incidents from the last 14 days
        self.status.add_message("Fetching incidents from the last 14 days")
        recent_incidents = await self._get_recent_incidents(days=14)
        result["recent_incidents"] = recent_incidents
        result["recent_incidents_by_region"] = self._group_incidents_by_region(recent_incidents)
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
    
    async def _get_components(self) -> List[Dict[str, Any]]:
        """Fetch all Cloudflare components/services."""
        import aiohttp
        
        url = "https://www.cloudflarestatus.com/api/v2/components.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        components = data.get("components", [])
                        
                        return [
                            {
                                "id": comp["id"],
                                "name": comp["name"],
                                "status": comp["status"],
                                "description": comp.get("description", ""),
                                "group": comp.get("group", False),
                                "group_id": comp.get("group_id")
                            }
                            for comp in components
                        ]
                    else:
                        self.logger.error(f"Failed to fetch components: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching components: {e}")
            return []
    
    def _group_components_by_region(self, components: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group components by region, prioritizing US/North America.
        
        Cloudflare components often include region/location in their names.
        """
        regions = {
            "US/North America": [],
            "Europe": [],
            "Asia Pacific": [],
            "South America": [],
            "Africa": [],
            "Middle East": [],
            "Global/Other": []
        }
        
        # Region keywords for categorization
        region_keywords = {
            "US/North America": ["united states", "us-", "north america", "canada", "mexico", "usa"],
            "Europe": ["europe", "eu-", "uk", "germany", "france", "netherlands", "ireland"],
            "Asia Pacific": ["asia", "ap-", "japan", "singapore", "australia", "hong kong", "india"],
            "South America": ["south america", "brazil", "argentina", "sa-"],
            "Africa": ["africa", "south africa", "af-"],
            "Middle East": ["middle east", "uae", "dubai", "me-"]
        }
        
        for comp in components:
            name_lower = comp["name"].lower() if comp.get("name") else ""
            description_lower = comp.get("description", "").lower() if comp.get("description") else ""
            categorized = False
            
            # Check each region's keywords
            for region, keywords in region_keywords.items():
                if any(kw in name_lower or kw in description_lower for kw in keywords):
                    regions[region].append(comp)
                    categorized = True
                    break
            
            if not categorized:
                regions["Global/Other"].append(comp)
        
        # Remove empty regions
        return {region: comps for region, comps in regions.items() if comps}
    
    def _group_incidents_by_region(self, incidents: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group incidents by affected regions based on component names.
        
        Prioritizes US/North America incidents.
        """
        regions = {
            "US/North America": [],
            "Europe": [],
            "Asia Pacific": [],
            "South America": [],
            "Africa": [],
            "Middle East": [],
            "Global/Multiple Regions": []
        }
        
        region_keywords = {
            "US/North America": ["united states", "us-", "north america", "canada", "mexico", "usa"],
            "Europe": ["europe", "eu-", "uk", "germany", "france", "netherlands", "ireland"],
            "Asia Pacific": ["asia", "ap-", "japan", "singapore", "australia", "hong kong", "india"],
            "South America": ["south america", "brazil", "argentina", "sa-"],
            "Africa": ["africa", "south africa", "af-"],
            "Middle East": ["middle east", "uae", "dubai", "me-"]
        }
        
        for incident in incidents:
            components = incident.get("components", [])
            name_lower = incident.get("name", "").lower() if incident.get("name") else ""
            
            # If no components or "global" in name, it's global
            if not components or "global" in name_lower:
                regions["Global/Multiple Regions"].append(incident)
                continue
            
            # Check which regions are affected based on component names
            affected_regions = set()
            for comp_name in components:
                comp_name_lower = comp_name.lower()
                for region, keywords in region_keywords.items():
                    if any(kw in comp_name_lower for kw in keywords):
                        affected_regions.add(region)
            
            # If multiple regions or none detected, it's global
            if len(affected_regions) > 1 or len(affected_regions) == 0:
                regions["Global/Multiple Regions"].append(incident)
            else:
                region = list(affected_regions)[0]
                regions[region].append(incident)
        
        # Remove empty regions and prioritize US/North America
        filtered = {region: incs for region, incs in regions.items() if incs}
        
        # Reorder to put US/North America first
        if "US/North America" in filtered:
            ordered = {"US/North America": filtered.pop("US/North America")}
            ordered.update(filtered)
            return ordered
        
        return filtered
