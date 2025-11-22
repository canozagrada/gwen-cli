"""AWS agent for status monitoring."""

from typing import Any, Dict, List
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from .base import BaseAgent


class AWSAgent(BaseAgent):
    """
    Agent for interacting with AWS Service Health Dashboard.
    
    Monitors operational status via RSS feed from AWS Health Dashboard.
    """
    
    def __init__(self):
        super().__init__("AWSAgent")
    
    async def initialize(self) -> None:
        """Initialize AWS Health Dashboard RSS feed connection."""
        await super().initialize()
        self.status.add_message("Initializing AWS Service Health Dashboard client")
        self.status.add_message("AWS Service Health Dashboard client initialized")
    
    async def _execute_task(self) -> Dict[str, Any]:
        """
        Execute AWS status monitoring tasks.
        
        Returns:
            Dictionary containing AWS status and event information
        """
        self.status.add_message("Checking AWS operational status")
        
        # Get all events from RSS feed
        all_events = await self._get_events_from_rss()
        
        # Separate ongoing vs recent events
        ongoing_events = []
        recent_events = []
        
        from datetime import timezone
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)
        
        for event in all_events:
            pub_date = datetime.fromisoformat(event["published_date"])
            
            # Events without resolution are ongoing
            if event.get("status") in ["open", "ongoing", None]:
                ongoing_events.append(event)
            elif pub_date >= cutoff_date:
                recent_events.append(event)
        
        # Initialize result dictionary
        result = {
            "status": {
                "indicator": "minor" if len(ongoing_events) > 0 else "none",
                "description": f"{len(ongoing_events)} active event(s)" if ongoing_events else "All Systems Operational",
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            "ongoing_incidents": ongoing_events,
            "recent_incidents": recent_events,
            "scheduled_maintenance": []  # AWS RSS doesn't separate maintenance
        }
        
        if len(ongoing_events) > 0:
            self.status.add_message(f"Found {len(ongoing_events)} ongoing event(s)")
        else:
            self.status.add_message("All services operational")
        
        self.status.add_message(f"Found {len(recent_events)} resolved event(s) in the last 14 days")
        
        return result
    
    async def _get_events_from_rss(self) -> List[Dict[str, Any]]:
        """
        Fetch events from AWS Service Health Dashboard RSS feed.
        
        AWS provides a public RSS feed at https://health.aws.amazon.com/health/status
        that includes current and recent service events.
        """
        import aiohttp
        from datetime import timezone
        import re
        
        rss_url = "https://health.aws.amazon.com/health/status"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        
                        # AWS RSS feed has known issues with malformed XML
                        # Use regex to extract items directly instead of full XML parsing
                        items = []
                        
                        # Pattern to find item blocks
                        item_pattern = re.compile(r'<item>(.*?)</item>', re.DOTALL)
                        item_matches = item_pattern.findall(xml_content)
                        
                        for item_content in item_matches:
                            try:
                                # Extract fields using regex
                                title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', item_content)
                                link_match = re.search(r'<link>(.*?)</link>', item_content)
                                desc_match = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>', item_content, re.DOTALL)
                                pub_date_match = re.search(r'<pubDate>(.*?)</pubDate>', item_content)
                                guid_match = re.search(r'<guid.*?>(.*?)</guid>', item_content)
                                
                                if title_match and pub_date_match:
                                    title = title_match.group(1).strip()
                                    pub_date_str = pub_date_match.group(1).strip()
                                    
                                    # Parse pubDate
                                    pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z')
                                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                                    
                                    # Extract service and region from title
                                    service = "Unknown"
                                    region = "Global"
                                    
                                    if " - " in title:
                                        parts = title.split(" - ")
                                        if len(parts) >= 2:
                                            region = parts[-1].strip()
                                            service_part = " - ".join(parts[:-1])
                                            if ":" in service_part:
                                                service = service_part.split(":", 1)[1].strip()
                                    elif ":" in title:
                                        service = title.split(":", 1)[1].strip()
                                    
                                    # Determine status from title
                                    status = "resolved"
                                    if "Service Issue" in title or "Degraded" in title:
                                        status = "ongoing"
                                    elif "Resolved" in title:
                                        status = "resolved"
                                    
                                    items.append({
                                        "id": guid_match.group(1).strip() if guid_match else (link_match.group(1).strip() if link_match else ""),
                                        "title": title,
                                        "service": service,
                                        "region": region,
                                        "description": desc_match.group(1).strip() if desc_match else "",
                                        "link": link_match.group(1).strip() if link_match else "",
                                        "published": pub_date_str,
                                        "published_date": pub_date.isoformat(),
                                        "status": status
                                    })
                            except Exception as e:
                                self.logger.warning(f"Error parsing RSS item: {e}")
                                continue
                        
                        return items
                        
                        return events
                    else:
                        self.logger.error(f"Failed to fetch AWS RSS feed: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching AWS events: {e}")
            return []
