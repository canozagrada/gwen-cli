"""Azure agent for status monitoring."""

from typing import Any, Dict, List
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from .base import BaseAgent


class AzureAgent(BaseAgent):
    """
    Agent for interacting with Azure Status.
    
    Monitors operational status via RSS feed and Azure DevOps health API.
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
        
        # Check current status via RSS feed (for Azure public cloud)
        status_data = await self._get_azure_status()
        self.status.add_message(f"Status: {status_data['description']}")
        
        # Initialize result dictionary
        result = {
            "status": status_data,
            "unresolved_incidents": [],
            "recent_incidents": status_data.get("recent_incidents", [])
        }
        
        # RSS feed returns recent incidents directly
        recent_count = len(result["recent_incidents"])
        if recent_count > 0:
            self.status.add_message(f"Found {recent_count} recent incident(s) from RSS feed")
        else:
            self.status.add_message("No recent incidents")
        
        return result
    
    async def _get_azure_status(self) -> Dict[str, Any]:
        """Fetch current Azure operational status from RSS feed."""
        import aiohttp
        from datetime import timezone
        
        rss_url = "https://rssfeed.azure.status.microsoft/en-us/status/feed/"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        
                        # Parse RSS feed
                        root = ET.fromstring(xml_content)
                        
                        # Get all items (incidents) from RSS feed
                        items = root.findall('.//item')
                        
                        # Extract recent incidents (last 30 days)
                        cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
                        recent_incidents = []
                        
                        for item in items:
                            title_elem = item.find('title')
                            link_elem = item.find('link')
                            desc_elem = item.find('description')
                            pub_date_elem = item.find('pubDate')
                            
                            if title_elem is not None and pub_date_elem is not None:
                                try:
                                    # Parse pubDate (RFC 822 format)
                                    pub_date_str = pub_date_elem.text
                                    pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z')
                                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                                    
                                    if pub_date >= cutoff_date:
                                        recent_incidents.append({
                                            "title": title_elem.text,
                                            "link": link_elem.text if link_elem is not None else "",
                                            "description": desc_elem.text if desc_elem is not None else "",
                                            "published": pub_date_str,
                                            "published_date": pub_date.isoformat()
                                        })
                                except Exception as e:
                                    self.logger.warning(f"Error parsing RSS item: {e}")
                                    continue
                        
                        # Determine status based on items
                        if len(items) == 0:
                            indicator = "none"
                            description = "All Systems Operational"
                        else:
                            # Check if any incidents are recent (within 7 days)
                            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
                            recent_active = [i for i in recent_incidents if datetime.fromisoformat(i["published_date"]) >= week_ago]
                            
                            if recent_active:
                                indicator = "minor"
                                description = f"{len(recent_active)} recent incident(s) reported"
                            else:
                                indicator = "none"
                                description = "All Systems Operational"
                        
                        return {
                            "indicator": indicator,
                            "description": description,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "recent_incidents": recent_incidents[:7]  # Return max 7 most recent
                        }
                    else:
                        self.logger.error(f"Failed to fetch Azure RSS feed: {response.status}")
                        return {
                            "indicator": "unknown",
                            "description": "Unable to fetch status",
                            "updated_at": datetime.now().isoformat(),
                            "recent_incidents": []
                        }
        except Exception as e:
            self.logger.error(f"Error fetching Azure status: {e}")
            return {
                "indicator": "error",
                "description": f"Error: {str(e)}",
                "updated_at": datetime.now().isoformat(),
                "recent_incidents": []
            }
    
    async def _get_unresolved_incidents(self) -> List[Dict[str, Any]]:
        """Azure RSS feed doesn't distinguish unresolved, return empty list."""
        return []
    
    async def _get_recent_incidents(self, days: int = 7) -> List[Dict[str, Any]]:
        """Recent incidents are already fetched in _get_azure_status, return empty list."""
        return []
