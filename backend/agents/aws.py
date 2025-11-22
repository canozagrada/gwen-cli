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
        
        rss_url = "https://health.aws.amazon.com/health/status"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        
                        # Parse RSS feed
                        root = ET.fromstring(xml_content)
                        
                        # Get all items (events) from RSS feed
                        items = root.findall('.//item')
                        
                        events = []
                        for item in items:
                            title_elem = item.find('title')
                            link_elem = item.find('link')
                            desc_elem = item.find('description')
                            pub_date_elem = item.find('pubDate')
                            guid_elem = item.find('guid')
                            
                            if title_elem is not None and pub_date_elem is not None:
                                try:
                                    # Parse pubDate (RFC 822 format)
                                    pub_date_str = pub_date_elem.text
                                    pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z')
                                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                                    
                                    # Extract service and region from title
                                    # Format: "Service Issue: [Service Name] - [Region]"
                                    title = title_elem.text
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
                                    
                                    events.append({
                                        "id": guid_elem.text if guid_elem is not None else link_elem.text if link_elem is not None else "",
                                        "title": title,
                                        "service": service,
                                        "region": region,
                                        "description": desc_elem.text if desc_elem is not None else "",
                                        "link": link_elem.text if link_elem is not None else "",
                                        "published": pub_date_str,
                                        "published_date": pub_date.isoformat(),
                                        "status": status
                                    })
                                except Exception as e:
                                    self.logger.warning(f"Error parsing RSS item: {e}")
                                    continue
                        
                        return events
                    else:
                        self.logger.error(f"Failed to fetch AWS RSS feed: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching AWS events: {e}")
            return []
