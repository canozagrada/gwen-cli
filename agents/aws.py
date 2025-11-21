"""AWS agent for status monitoring."""

from typing import Any, Dict, List
from datetime import datetime, timedelta

from .base import BaseAgent


class AWSAgent(BaseAgent):
    """
    Agent for interacting with AWS Health Dashboard API.
    
    Monitors operational status and service events.
    """
    
    def __init__(self):
        super().__init__("AWSAgent")
    
    async def initialize(self) -> None:
        """Initialize AWS Health Dashboard API connection."""
        await super().initialize()
        self.status.add_message("Initializing AWS Health Dashboard API client")
        self.status.add_message("AWS Health Dashboard API client initialized")
    
    async def _execute_task(self) -> Dict[str, Any]:
        """
        Execute AWS status monitoring tasks.
        
        Returns:
            Dictionary containing AWS status and event information
        """
        self.status.add_message("Checking AWS operational status")
        
        # Get current events
        current_events = await self._get_current_events()
        
        # Initialize result dictionary
        result = {
            "current_events": current_events,
            "recent_events": []
        }
        
        if len(current_events) > 0:
            self.status.add_message(f"Found {len(current_events)} current event(s)")
        else:
            self.status.add_message("All services operational")
        
        # Get events from the last 14 days
        self.status.add_message("Fetching events from the last 14 days")
        recent_events = await self._get_recent_events(days=14)
        result["recent_events"] = recent_events
        self.status.add_message(f"Found {len(recent_events)} event(s) in the last 14 days")
        
        return result
    
    async def _get_current_events(self) -> List[Dict[str, Any]]:
        """Fetch current events from AWS Health Dashboard API."""
        import aiohttp
        
        url = "https://health.aws.amazon.com/public/currentevents"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        events = await response.json()
                        
                        # Extract key information from events
                        return [
                            {
                                "service": event.get("service", "Unknown"),
                                "summary": event.get("summary", ""),
                                "date": event.get("date", ""),
                                "status": event.get("status", ""),
                                "details": event.get("details", ""),
                                "region": event.get("region", "")
                            }
                            for event in events
                        ]
                    else:
                        self.logger.error(f"Failed to fetch current events: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching current events: {e}")
            return []
    
    async def _get_recent_events(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Fetch events from the last N days.
        
        Note: AWS Health Dashboard API doesn't provide historical events via public API.
        This method filters current events by date.
        """
        import aiohttp
        from datetime import timezone
        
        url = "https://health.aws.amazon.com/public/currentevents"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        events = await response.json()
                        
                        # Calculate cutoff date (timezone-aware)
                        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                        
                        # Filter events from the last N days
                        recent_events = []
                        for event in events:
                            # Parse event date (format: Unix timestamp in milliseconds)
                            if "date" in event and event["date"]:
                                try:
                                    event_date = datetime.fromtimestamp(event["date"] / 1000, tz=timezone.utc)
                                    
                                    if event_date >= cutoff_date:
                                        recent_events.append({
                                            "service": event.get("service", "Unknown"),
                                            "summary": event.get("summary", ""),
                                            "date": event.get("date", ""),
                                            "status": event.get("status", ""),
                                            "details": event.get("details", ""),
                                            "region": event.get("region", ""),
                                            "event_date": event_date.isoformat()
                                        })
                                except (ValueError, TypeError) as e:
                                    self.logger.error(f"Error parsing event date: {e}")
                        
                        return recent_events
                    else:
                        self.logger.error(f"Failed to fetch events: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Error fetching recent events: {e}")
            return []
