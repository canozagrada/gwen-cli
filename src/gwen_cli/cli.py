#!/usr/bin/env python3
"""
Gwen CLI - Multi-Agent Cloud Status Monitor

A command-line interface for monitoring cloud service status across
multiple providers using the Gwen agent orchestration system.
"""

import argparse
import asyncio
from typing import Optional, List
import aiohttp
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

# Backend API base URL
API_BASE = "http://127.0.0.1:8000"


async def fetch_api(endpoint: str, method: str = "GET") -> dict:
    """Fetch data from the backend API."""
    url = f"{API_BASE}{endpoint}"
    
    try:
        async with aiohttp.ClientSession() as session:
            if method == "POST":
                async with session.post(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        console.print(f"[red]API Error: {response.status}[/red]")
                        return None
            else:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        console.print(f"[red]API Error: {response.status}[/red]")
                        return None
    except aiohttp.ClientConnectorError:
        console.print("[red]Error: Cannot connect to backend API[/red]")
        console.print("[yellow]Make sure the backend is running: cd backend && python -m uvicorn main:app[/yellow]")
        return None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return None


def format_timestamp(iso_str: Optional[str]) -> str:
    """Format ISO timestamp to human-readable format."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return iso_str


def get_status_emoji(indicator: str) -> str:
    """Get emoji for status indicator."""
    emojis = {
        "none": "✅",
        "minor": "⚠️",
        "major": "🔴",
        "critical": "🚨",
        "unknown": "❓",
        "error": "❌"
    }
    return emojis.get(indicator, "❓")


async def cmd_status(args):
    """Show current status of all agents or a specific agent."""
    console.print("\n[bold cyan]Gwen Multi-Agent Status Monitor[/bold cyan]\n")
    
    if args.agent:
        # Show specific agent status
        data = await fetch_api(f"/agents/{args.agent}/execute", method="POST")
        if not data:
            return
        
        # Show agent status
        status_emoji = get_status_emoji(data.get("state", "unknown"))
        console.print(f"{status_emoji} [bold]{args.agent}[/bold] - {data.get('state', 'unknown')}")
        
        if data.get("error_message"):
            console.print(f"[red]Error: {data['error_message']}[/red]\n")
            return
        
        # Show execution info
        if data.get("raw_output"):
            output = data["raw_output"]
            
            if "status" in output:
                status = output["status"]
                console.print(f"\n[bold]Overall Status:[/bold] {status.get('description', 'N/A')}")
                console.print(f"[dim]Updated: {format_timestamp(status.get('updated_at'))}[/dim]")
            
            # Show ongoing incidents
            ongoing = output.get("ongoing_incidents", [])
            if ongoing:
                console.print(f"\n[bold red]Ongoing Incidents: {len(ongoing)}[/bold red]")
                for inc in ongoing[:5]:  # Show first 5
                    console.print(f"  • {inc.get('name', 'Unnamed incident')}")
            
            # Show non-operational components (for services like Cloudflare)
            non_op_components = output.get("non_operational_components_by_region", {})
            if non_op_components:
                console.print(f"\n[bold yellow]Non-Operational Components:[/bold yellow]")
                for region, comps in non_op_components.items():
                    # Group by status
                    by_status = {}
                    for comp in comps:
                        status = comp.get("status", "unknown")
                        if status not in by_status:
                            by_status[status] = []
                        by_status[status].append(comp)
                    
                    console.print(f"\n  [cyan]{region}:[/cyan]")
                    for status, comps_with_status in by_status.items():
                        # Extract location codes (text in parentheses like (DTW), (ORF))
                        import re
                        locations = []
                        for comp in comps_with_status:
                            match = re.search(r'\(([A-Z]{3})\)', comp.get('name', ''))
                            if match:
                                locations.append(match.group(1))
                            else:
                                locations.append(comp.get('name', 'Unknown')[:30])
                        
                        locations_str = ', '.join(locations)
                        console.print(f"    {status.replace('_', ' ').title()}: {locations_str}")
            
            # Show scheduled maintenance
            maintenance = output.get("scheduled_maintenance", [])
            if maintenance:
                # Sort by scheduled_for date (soonest first)
                sorted_maintenance = sorted(
                    maintenance,
                    key=lambda m: m.get("scheduled_for", "9999-99-99")
                )
                
                console.print(f"\n[bold yellow]Scheduled Maintenance: {len(maintenance)}[/bold yellow]")
                for maint in sorted_maintenance[:3]:  # Show first 3 soonest
                    in_progress = "🔧 IN PROGRESS" if maint.get("in_progress") else "📅 Upcoming"
                    console.print(f"  {in_progress}: {maint.get('name', 'Unnamed')}")
        
    else:
        # Execute all agents and show summary
        data = await fetch_api("/retrieve-status", method="POST")
        if not data:
            return
        
        # Create status table
        table = Table(title="Cloud Service Status", box=box.ROUNDED)
        table.add_column("Service", style="cyan", no_wrap=True)
        table.add_column("Status", style="green")
        table.add_column("Components", style="yellow")
        table.add_column("Incidents", justify="right")
        table.add_column("Maintenance", justify="right")
        table.add_column("Last Updated", style="dim")
        
        for agent_summary in data.get("agent_summaries", []):
            agent_name = agent_summary.get("agent_name", "Unknown").replace("Agent", "")
            status = agent_summary.get("status", "unknown")
            
            # Get the actual output data
            output = agent_summary.get("raw_output", {})
            
            # Count incidents and maintenance from actual data
            ongoing_incidents = len(output.get("ongoing_incidents", []))
            recent_incidents = len(output.get("recent_incidents", []))
            total_incidents = ongoing_incidents + recent_incidents
            scheduled_maintenance = len(output.get("scheduled_maintenance", []))
            
            # Check for non-operational components
            non_op_components = output.get("non_operational_components", [])
            component_status = "✓ All OK"
            if non_op_components:
                # Count by status type
                status_counts = {}
                for comp in non_op_components:
                    comp_status = comp.get("status", "unknown")
                    status_counts[comp_status] = status_counts.get(comp_status, 0) + 1
                
                # Format as compact summary
                total = len(non_op_components)
                if len(status_counts) == 1:
                    # Single status type
                    status_type = list(status_counts.keys())[0]
                    short_status = status_type.replace("_", "-").replace("partial-outage", "outage").replace("under-maintenance", "maint")
                    component_status = f"⚠ {total} {short_status}"
                else:
                    # Multiple status types - just show total with icon
                    component_status = f"⚠ {total} issues"
            
            # Determine status indicator from output
            status_indicator = "none"
            if output.get("status"):
                status_indicator = output["status"].get("indicator", "none")
            
            status_emoji = get_status_emoji(status_indicator)
            
            # Format status text
            if ongoing_incidents > 0:
                status_text = f"{status_emoji} {ongoing_incidents} ongoing"
            elif status_indicator == "none":
                status_text = f"{status_emoji} Operational"
            else:
                status_text = f"{status_emoji} {status_indicator}"
            
            table.add_row(
                agent_name,
                status_text,
                component_status,
                str(total_incidents) if total_incidents > 0 else "0",
                str(scheduled_maintenance) if scheduled_maintenance > 0 else "0",
                format_timestamp(agent_summary.get("end_time"))
            )
        
        console.print(table)
        
        # Show hint if any service has component issues
        has_component_issues = any(
            len(summary.get("raw_output", {}).get("non_operational_components", [])) > 0
            for summary in data.get("agent_summaries", [])
        )
        if has_component_issues:
            console.print("\n[dim]💡 Tip: Run 'gwen status <ServiceName>Agent' for detailed component status[/dim]")
        
        console.print(f"\n[dim]Execution ID: {data.get('execution_id')}[/dim]")
        console.print(f"[dim]Duration: {data.get('total_duration', 0):.2f}s[/dim]")


async def cmd_incidents(args):
    """Show incidents for all agents or a specific agent."""
    console.print("\n[bold cyan]Cloud Service Incidents[/bold cyan]\n")
    
    # Execute agents to get latest data
    if args.agent:
        data = await fetch_api(f"/agents/{args.agent}/execute", method="POST")
        if not data or not data.get("raw_output"):
            return
        
        agents_data = {args.agent: data["raw_output"]}
    else:
        result = await fetch_api("/retrieve-status", method="POST")
        if not result:
            return
        
        # Get detailed data for each agent
        agents_data = {}
        for agent_summary in result.get("agent_summaries", []):
            agent_name = agent_summary.get("agent_name")
            if agent_summary.get("raw_output"):
                agents_data[agent_name] = agent_summary["raw_output"]
    
    # Display incidents
    found_any = False
    for agent_name, output in agents_data.items():
        service_name = agent_name.replace("Agent", "")
        
        ongoing = output.get("ongoing_incidents", [])
        recent = output.get("recent_incidents", [])
        
        # Skip if no incidents to show
        if not ongoing and not (args.show_recent and recent):
            continue
        
        found_any = True
        console.print(f"\n[bold]{service_name}[/bold]")
        console.print("-" * 60)
        
        if ongoing:
            console.print(f"\n[red]● Ongoing ({len(ongoing)}):[/red]")
            for inc in ongoing:
                console.print(f"  [bold]{inc.get('name', 'Unnamed')}[/bold]")
                console.print(f"  Impact: {inc.get('impact', 'unknown')} | Status: {inc.get('status', 'unknown')}")
                console.print(f"  Created: {format_timestamp(inc.get('created_at'))}")
                if inc.get('components'):
                    console.print(f"  Components: {', '.join(inc['components'][:3])}")
                if inc.get('shortlink'):
                    console.print(f"  Link: {inc['shortlink']}")
                console.print()
        
        if args.show_recent and recent:
            console.print(f"\n[yellow]○ Recent (last {args.days} days - {len(recent)}):[/yellow]")
            for inc in recent[:5]:  # Show first 5
                console.print(f"  {inc.get('name', 'Unnamed')}")
                console.print(f"  Resolved: {format_timestamp(inc.get('resolved_at'))}")
                console.print()
    
    if not found_any:
        if args.show_recent:
            console.print("[green]No incidents found in the last {} days[/green]".format(args.days))
        else:
            console.print("[green]✅ No ongoing incidents! All services operational.[/green]")
            console.print("\n[dim]💡 Tip: Use --show-recent to see resolved incidents[/dim]")


async def cmd_maintenance(args):
    """Show scheduled maintenance for all agents or a specific agent."""
    console.print("\n[bold cyan]Scheduled Maintenance[/bold cyan]\n")
    
    # Execute agents to get latest data
    if args.agent:
        data = await fetch_api(f"/agents/{args.agent}/execute", method="POST")
        if not data or not data.get("raw_output"):
            return
        
        agents_data = {args.agent: data["raw_output"]}
    else:
        result = await fetch_api("/retrieve-status", method="POST")
        if not result:
            return
        
        # Get detailed data for each agent
        agents_data = {}
        for agent_summary in result.get("agent_summaries", []):
            agent_name = agent_summary.get("agent_name")
            if agent_summary.get("raw_output"):
                agents_data[agent_name] = agent_summary["raw_output"]
    
    # Display maintenance
    found_any = False
    for agent_name, output in agents_data.items():
        service_name = agent_name.replace("Agent", "")
        maintenance = output.get("scheduled_maintenance", [])
        
        if not maintenance:
            continue
        
        found_any = True
        console.print(f"\n[bold]{service_name}[/bold]")
        console.print("-" * 60)
        
        # Sort by scheduled_for date (soonest first), with in-progress items first
        sorted_maintenance = sorted(
            maintenance,
            key=lambda m: (
                not m.get("in_progress", False),  # in_progress=True comes first (False < True)
                m.get("scheduled_for", "9999-99-99")  # Then sort by date
            )
        )
        
        # Group maintenance by region
        from collections import defaultdict
        import re
        
        # Group by region (check more specific regions first to avoid mismatches)
        region_keywords = {
            "Middle East": ["uae", "saudi arabia", "israel", "turkey", "qatar", "kuwait", "bahrain", "oman", "jordan", "lebanon", "iraq", "iran", "georgia", "azerbaijan", "armenia", "amman", "baghdad", "tbilisi"],
            "North America": [" us ", " usa ", " united states", ", us", "virginia", "california", "texas", "florida", "illinois", "washington", "new york", "oregon", "colorado", "nevada", "arizona", "ohio", "pennsylvania", "tennessee", "massachusetts", "michigan", "north carolina", "richmond", "ashburn", "chicago", "los angeles", "newark", "dallas", "san jose", "seattle", "miami"],
            "Latin America & Caribbean": ["brazil", "argentina", "chile", "colombia", "peru", "costa rica", "panama", "ecuador", "venezuela", "uruguay", "bolivia", "paraguay", "guatemala", "honduras", "nicaragua", "el salvador", "dominican republic", "puerto rico", "cuba", "jamaica", "mexico", "buenos aires", "bogota", "lima", "curitiba", "são paulo", "medellín", "san josé", "queretaro", "arica", "timbó"],
            "Europe": ["united kingdom", "uk", "germany", "france", "netherlands", "spain", "italy", "belgium", "switzerland", "sweden", "norway", "denmark", "finland", "poland", "austria", "ireland", "portugal", "greece", "iceland", "czech republic", "hungary", "romania", "frankfurt", "stuttgart", "amsterdam", "reykjavík", "london", "palermo", "marseille", "paris"],
            "Asia": ["china", "japan", "south korea", "india", "singapore", "hong kong", "thailand", "vietnam", "malaysia", "indonesia", "philippines", "taiwan", "pakistan", "bangladesh", "nepal", "sri lanka", "cambodia", "myanmar", "mumbai", "kuala lumpur", "nagpur", "karachi", "seoul"],
            "Oceania": ["australia", "new zealand", "fiji", "papua new guinea", "samoa", "guam", "maldives", "male"],
            "Africa": ["south africa", "egypt", "nigeria", "kenya", "morocco", "tunisia", "algeria", "ethiopia", "ghana", "tanzania", "uganda"]
        }
        
        regions = defaultdict(list)
        
        for maint in sorted_maintenance:
            # Extract location name from maintenance name
            name = maint.get('name', '').lower()
            components = maint.get('components', [])
            location_text = (name + " " + " ".join(components)).lower()
            
            # Determine region
            region = "Other"
            for region_name, keywords in region_keywords.items():
                if any(kw in location_text for kw in keywords):
                    region = region_name
                    break
            
            # Extract code (e.g., DFW, LAX, etc.)
            code_match = re.search(r'\(([A-Z]{3})\)', maint.get('name', ''))
            if code_match:
                code = code_match.group(1)
            else:
                # Try to extract first word as fallback
                name_parts = maint.get('name', 'Unknown').split()
                code = name_parts[0][:3].upper() if name_parts else 'UNK'
            
            regions[region].append({
                'code': code,
                'full_name': maint.get('name', 'Unknown'),
                'in_progress': maint.get('in_progress', False),
                'scheduled_for': maint.get('scheduled_for'),
                'scheduled_until': maint.get('scheduled_until'),
                'shortlink': maint.get('shortlink')
            })
        
        # Display by region
        region_order = ["North America", "Latin America & Caribbean", "Europe", "Asia", "Middle East", "Oceania", "Africa", "Other"]
        
        for region_name in region_order:
            if region_name not in regions:
                continue
            
            items = regions[region_name]
            codes = [item['code'] for item in items]
            in_progress_count = sum(1 for item in items if item['in_progress'])
            
            status_text = f"[red]{in_progress_count} in progress, [/red]" if in_progress_count > 0 else ""
            console.print(f"\n[cyan]{region_name}:[/cyan] {status_text}{len(items)} scheduled")
            
            # Show codes in a compact list
            codes_str = ', '.join(codes)
            console.print(f"  Locations: {codes_str}")
            
            # Show date range
            dates = sorted(set(item['scheduled_for'][:10] for item in items if item['scheduled_for']))
            if dates:
                date_range = f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else dates[0]
                console.print(f"  [dim]Dates: {date_range}[/dim]")
    
    if not found_any:
        console.print("[green]No scheduled maintenance found[/green]")


def show_help():
    """Display detailed help with examples and quick reference."""
    from rich.panel import Panel
    from rich.columns import Columns
    
    console.print("\n[bold cyan]Gwen Multi-Agent Status Monitor[/bold cyan]\n")
    console.print("Track cloud service status across Cloudflare, AWS, Azure, GCP, GitHub, Datadog, and Atlassian.\n")
    
    # Quick reference table
    help_table = Table(title="Command Reference", box=box.ROUNDED, show_header=True)
    help_table.add_column("Command", style="cyan", no_wrap=True)
    help_table.add_column("Description", style="white")
    help_table.add_column("Example", style="dim")
    
    help_table.add_row(
        "status [agent]",
        "Show current status summary",
        "gwen status\ngwen status CloudflareAgent"
    )
    help_table.add_row(
        "incidents [agent]",
        "Display ongoing and recent incidents",
        "gwen incidents\ngwen incidents --show-recent"
    )
    help_table.add_row(
        "maintenance [agent]",
        "Show scheduled maintenance windows",
        "gwen maintenance\ngwen maintenance AzureAgent"
    )
    help_table.add_row(
        "list-agents",
        "List all available agents",
        "gwen list-agents"
    )
    
    console.print(help_table)
    
    # Quick tips
    console.print("\n[bold yellow]💡 Quick Tips:[/bold yellow]\n")
    console.print("  • Use [cyan]gwen status[/cyan] for a quick overview of all services")
    console.print("  • Add agent name for detailed view: [cyan]gwen status CloudflareAgent[/cyan]")
    console.print("  • Use [cyan]--show-recent[/cyan] with incidents to see resolved issues")
    console.print("  • Component issues show even when overall status is operational")
    console.print("  • Maintenance windows are sorted by date (soonest first)")
    
    # Available agents
    console.print("\n[bold]Available Agents:[/bold]")
    agent_names = "CloudflareAgent, AzureAgent, AWSAgent, GCPAgent, GitHubAgent, DatadogAgent, AtlassianAgent"
    console.print(f"  {agent_names}")
    
    console.print("\n[dim]Backend must be running: cd backend && python -m uvicorn main:app --port 8000[/dim]\n")


async def cmd_list_agents(args):
    """List all available agents."""
    console.print("\n[bold cyan]Available Agents[/bold cyan]\n")
    
    data = await fetch_api("/agents")
    if not data:
        console.print("[yellow]Tip: Make sure the backend is running:[/yellow]")
        console.print("[dim]cd backend && python -m uvicorn main:app --port 8000[/dim]")
        return
    
    table = Table(box=box.ROUNDED)
    table.add_column("Agent", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Description")
    
    for agent in data.get("agents", []):
        table.add_row(
            agent.get("name", "Unknown"),
            agent.get("type", "Unknown"),
            agent.get("status", "idle"),
            agent.get("description", "N/A")
        )
    
    console.print(table)
    console.print(f"\n[dim]Total agents: {data.get('total', 0)}[/dim]")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Gwen - Multi-Agent Cloud Status Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show current status of cloud services")
    status_parser.add_argument("agent", nargs="?", help="Specific agent name (e.g., CloudflareAgent)")
    
    # Incidents command
    incidents_parser = subparsers.add_parser("incidents", help="Show incidents")
    incidents_parser.add_argument("agent", nargs="?", help="Specific agent name")
    incidents_parser.add_argument("--days", type=int, default=14, help="Number of days to look back (default: 14)")
    incidents_parser.add_argument("--show-recent", action="store_true", help="Show recent resolved incidents")
    
    # Maintenance command
    maintenance_parser = subparsers.add_parser("maintenance", help="Show scheduled maintenance")
    maintenance_parser.add_argument("agent", nargs="?", help="Specific agent name")
    
    # list-agents command
    list_parser = subparsers.add_parser("list-agents", help="List all available monitoring agents")
    
    # help command
    help_parser = subparsers.add_parser("help", help="Show detailed command help and examples")
    
    args = parser.parse_args()
    
    # If no command, show help
    if not args.command:
        show_help()
        return
    
    # Execute command
    if args.command == "status":
        asyncio.run(cmd_status(args))
    elif args.command == "incidents":
        asyncio.run(cmd_incidents(args))
    elif args.command == "maintenance":
        asyncio.run(cmd_maintenance(args))
    elif args.command == "list-agents":
        asyncio.run(cmd_list_agents(args))
    elif args.command == "help":
        show_help()
    else:
        console.print("\n[yellow]No command specified. Use 'help' to see available commands.[/yellow]\n")
        parser.print_help()


if __name__ == "__main__":
    main()
