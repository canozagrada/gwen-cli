"""Azure agent for status monitoring."""

from typing import Any, Dict, List
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from .base import BaseAgent


class AzureAgent(BaseAgent):
    """
    Agent for interacting with Azure Status API.
    
    Monitors operational status via Statuspage.io v2 API and RSS feed fallback.
    """
    
    def __init__(self):
        super().__init__("AzureAgent")
    
    async def initialize(self) -> None:
        """Initialize Azure Status API connection."""
        await super().initialize()
        self.status.add_message("Initializing Azure Status API client")
        self.status.add_message("Azure Status API client initialized")
    
    async def _execute_task(self) -> Dict[str, Any]:
        """
        Execute Azure status monitoring tasks.
        
        Returns:
            Dictionary containing Azure status and incident information
        """
        self.status.add_message("Checking Azure operational status")
        
        # Check current status
        status_data = await self._get_azure_status()
        self.status.add_message(f"Status: {status_data['description']}")
        
        # Get scheduled maintenance
        scheduled = await self._get_scheduled_maintenance()
        in_progress_count = sum(1 for m in scheduled if m.get("in_progress", False))
        
        # Update status description if maintenance is happening
        original_status = status_data['description']
        if in_progress_count > 0:
            status_data['description'] = f"{original_status} ({in_progress_count} scheduled maintenance in progress)"
            self.status.add_message(f"Status: {status_data['description']}")
        
        # Initialize result dictionary
        result = {
            "status": status_data,
            "ongoing_incidents": [],
            "recent_incidents": [],
            "scheduled_maintenance": scheduled
        }
        
        # If not operational, get unresolved incidents
        if status_data['indicator'] != "none":
            self.status.add_message("System not operational - fetching unresolved incidents")
            unresolved = await self._get_unresolved_incidents()
            result["ongoing_incidents"] = unresolved
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
    
    async def _get_azure_status(self) -> Dict[str, Any]:
        """Fetch current Azure operational status."""
        import aiohttp
        
        # Azure uses a different status page structure, not Statuspage.io
        # We'll use the RSS feed as primary source
        url = "https://azure.status.microsoft/en-us/status/feed/"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        
                        # Parse RSS feed
                        root = ET.fromstring(xml_content)
                        
                        # Get recent items
                        items = root.findall('.//item')
                        
                        # Check if any items are from the last 24 hours
                        from datetime import timezone
                        now = datetime.now(timezone.utc)
                        day_ago = now - timedelta(days=1)
                        
                        recent_issues = 0
                        for item in items[:10]:  # Check first 10 items
                            pub_date_elem = item.find('pubDate')
                            if pub_date_elem is not None:
                                try:
                                    pub_date = datetime.strptime(pub_date_elem.text, '%a, %d %b %Y %H:%M:%S %Z')
                                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                                    if pub_date >= day_ago:
                                        recent_issues += 1
                                except:
                                    pass
                        
                        if recent_issues > 0:
                            return {
                                "indicator": "minor",
                                "description": f"{recent_issues} recent issue(s) reported",
                                "updated_at": now.isoformat()
                            }
                        else:
                            return {
                                "indicator": "none",
                                "description": "All Systems Operational",
                                "updated_at": now.isoformat()
                            }
                    else:
                        self.logger.error(f"Failed to fetch Azure RSS feed: {response.status}")
                        return {
                            "indicator": "unknown",
                            "description": "Unable to fetch status",
                            "updated_at": datetime.now().isoformat()
                        }
        except Exception as e:
            self.logger.error(f"Error fetching Azure status: {e}")
            return {
                "indicator": "error",
                "description": f"Error: {str(e)}",
                "updated_at": datetime.now().isoformat()
            }
    
    async def _get_unresolved_incidents(self) -> List[Dict[str, Any]]:
        """Fetch unresolved incidents from Azure RSS feed."""
        import aiohttp
        from datetime import timezone
        
        url = "https://azure.status.microsoft/en-us/status/feed/"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        root = ET.fromstring(xml_content)
                        items = root.findall('.//item')
                        
                        # Look for items that indicate ongoing issues
                        ongoing = []
                        for item in items[:20]:  # Check first 20 items
                            title_elem = item.find('title')
                            link_elem = item.find('link')
                            desc_elem = item.find('description')
                            pub_date_elem = item.find('pubDate')
                            
                            if title_elem is not None:
                                title = title_elem.text or ""
                                # Look for keywords indicating ongoing issues
                                if any(kw in title.lower() for kw in ['investigating', 'identified', 'monitoring', 'ongoing', 'degraded', 'outage']):
                                    pub_date_str = pub_date_elem.text if pub_date_elem is not None else ""
                                    ongoing.append({
                                        "id": link_elem.text if link_elem is not None else "",
                                        "name": title,
                                        "status": "investigating",
                                        "impact": "minor",
                                        "created_at": pub_date_str,
                                        "updated_at": pub_date_str,
                                        "shortlink": link_elem.text if link_elem is not None else "",
                                        "components": []
                                    })
                        
                        return ongoing
                    else:
                        self.logger.error(f"Failed to fetch Azure incidents: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching Azure unresolved incidents: {e}")
            return []
    
    async def _get_recent_incidents(self, days: int = 14) -> List[Dict[str, Any]]:
        """Fetch incidents from the last N days from RSS feed."""
        import aiohttp
        from datetime import timezone
        
        url = "https://azure.status.microsoft/en-us/status/feed/"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        root = ET.fromstring(xml_content)
                        items = root.findall('.//item')
                        
                        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                        recent = []
                        
                        for item in items:
                            title_elem = item.find('title')
                            link_elem = item.find('link')
                            desc_elem = item.find('description')
                            pub_date_elem = item.find('pubDate')
                            
                            if title_elem is not None and pub_date_elem is not None:
                                try:
                                    pub_date = datetime.strptime(pub_date_elem.text, '%a, %d %b %Y %H:%M:%S %Z')
                                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                                    
                                    if pub_date >= cutoff_date:
                                        title = title_elem.text or ""
                                        # Check if it's a resolution
                                        status = "resolved" if "resolved" in title.lower() else "ongoing"
                                        
                                        recent.append({
                                            "id": link_elem.text if link_elem is not None else "",
                                            "name": title,
                                            "status": status,
                                            "impact": "minor",
                                            "created_at": pub_date.isoformat(),
                                            "resolved_at": pub_date.isoformat() if status == "resolved" else None,
                                            "shortlink": link_elem.text if link_elem is not None else "",
                                            "components": [],
                                            "updates_count": 1
                                        })
                                except:
                                    pass
                        
                        return recent
                    else:
                        self.logger.error(f"Failed to fetch Azure incidents: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching recent incidents: {e}")
            return []
    
    async def _get_scheduled_maintenance(self) -> List[Dict[str, Any]]:
        """Fetch scheduled maintenance windows."""
        # Azure doesn't provide a structured maintenance API
        # Look for maintenance announcements in RSS feed
        import aiohttp
        from datetime import timezone
        
        url = "https://azure.status.microsoft/en-us/status/feed/"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        root = ET.fromstring(xml_content)
                        items = root.findall('.//item')
                        
                        maintenance = []
                        for item in items[:20]:
                            title_elem = item.find('title')
                            link_elem = item.find('link')
                            pub_date_elem = item.find('pubDate')
                            
                            if title_elem is not None:
                                title = title_elem.text or ""
                                # Look for maintenance keywords
                                if any(kw in title.lower() for kw in ['maintenance', 'scheduled', 'planned']):
                                    pub_date_str = pub_date_elem.text if pub_date_elem is not None else ""
                                    
                                    maintenance.append({
                                        "id": link_elem.text if link_elem is not None else "",
                                        "name": title,
                                        "status": "scheduled",
                                        "scheduled_for": pub_date_str,
                                        "scheduled_until": None,
                                        "in_progress": False,
                                        "impact": "maintenance",
                                        "components": [],
                                        "shortlink": link_elem.text if link_elem is not None else ""
                                    })
                        
                        return maintenance
                    else:
                        self.logger.error(f"Failed to fetch scheduled maintenance: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching scheduled maintenance: {e}")
            return []
