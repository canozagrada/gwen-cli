"""GWEN - a command-line monitor for public cloud status feeds."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime

from rich import box
from rich.console import Console
from rich.table import Table

from . import providers, regions
from .providers import CRITICAL, MAJOR, MINOR, OK, UNKNOWN, ProviderStatus

console = Console()

ICONS = {OK: "[green]OK[/green]", MINOR: "[yellow]MINOR[/yellow]",
         MAJOR: "[red]MAJOR[/red]", CRITICAL: "[bold red]CRITICAL[/bold red]",
         UNKNOWN: "[dim]UNKNOWN[/dim]"}

DASH = "[dim]--[/dim]"


def when(moment: datetime | None) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC" if moment else "n/a"


def when_short(moment: datetime | None) -> str:
    """Compact form for table cells, which are tight on width."""
    return f"{moment:%m-%d %H:%M}Z" if moment else "n/a"


def fetch(names: list[str] | None, days: int) -> list[ProviderStatus]:
    return asyncio.run(providers.gather(names, days))


def report_errors(results: list[ProviderStatus]) -> bool:
    """Print any feeds that could not be read. Returns True if any failed."""
    failed = [r for r in results if r.error]
    for result in failed:
        console.print(f"[yellow]![/yellow] {result.name}: {result.error}")
    return bool(failed)


def cmd_status(args) -> int:
    names = [args.provider] if args.provider else None
    results = fetch(names, days=args.days)

    if args.provider:
        show_detail(results[0])
    else:
        show_summary(results)

    return 1 if report_errors(results) else 0


def show_summary(results: list[ProviderStatus]) -> None:
    table = Table(title="Cloud Service Status", box=box.ROUNDED)
    table.add_column("Service", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Components")
    table.add_column("Incidents", justify="right")
    table.add_column("Maintenance", justify="right")
    table.add_column("Updated", style="dim", no_wrap=True)

    for result in results:
        if not result.supports_components:
            components = DASH
        elif result.degraded:
            components = f"[yellow]{len(result.degraded)} degraded[/yellow]"
        else:
            components = "[green]all OK[/green]"

        incidents = str(len(result.ongoing) + len(result.recent))
        maintenance = str(len(result.maintenance)) if result.supports_maintenance else DASH

        table.add_row(
            result.name,
            ICONS.get(result.indicator, result.indicator),
            components,
            incidents,
            maintenance,
            when_short(result.updated_at),
        )

    console.print(table)

    if any(r.degraded for r in results):
        console.print("\n[dim]Run 'gwen status <provider>' for component detail.[/dim]")
    if any(not (r.supports_maintenance and r.supports_components) for r in results):
        console.print(f"[dim]{DASH} means the provider does not publish that data.[/dim]")


def show_detail(result: ProviderStatus) -> None:
    console.print(
        f"\n{ICONS.get(result.indicator, result.indicator)} "
        f"[bold]{result.name}[/bold] - {result.description or 'no description'}"
    )
    console.print(f"[dim]Updated: {when(result.updated_at)}[/dim]")

    if result.error:
        return

    if result.ongoing:
        console.print(f"\n[bold red]Ongoing incidents ({len(result.ongoing)})[/bold red]")
        for incident in result.ongoing:
            console.print(f"  - {incident.name}")
            if incident.url:
                console.print(f"    [dim]{incident.url}[/dim]")

    if result.degraded:
        console.print(f"\n[bold yellow]Degraded components ({len(result.degraded)})[/bold yellow]")
        grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for component in result.degraded:
            region = regions.classify(component.name)
            grouped[region][component.status].append(regions.location_code(component.name))

        for region in regions.ORDER:
            if region not in grouped:
                continue
            console.print(f"\n  [cyan]{region}[/cyan]")
            for status, codes in sorted(grouped[region].items()):
                label = status.replace("_", " ").title()
                console.print(f"    {label}: {', '.join(sorted(codes))}")

    if result.maintenance:
        upcoming = sorted(
            result.maintenance,
            key=lambda m: (not m.in_progress, m.scheduled_for or datetime.max),
        )
        console.print(f"\n[bold yellow]Scheduled maintenance ({len(upcoming)})[/bold yellow]")
        for window in upcoming[:5]:
            marker = "[red]in progress[/red]" if window.in_progress else "upcoming"
            console.print(f"  {marker}: {window.name}")
        if len(upcoming) > 5:
            console.print(f"  [dim]... and {len(upcoming) - 5} more (see 'gwen maintenance')[/dim]")


def cmd_incidents(args) -> int:
    names = [args.provider] if args.provider else None
    results = fetch(names, days=args.days if args.show_recent else 0)

    found = False
    for result in results:
        recent = result.recent if args.show_recent else []
        if not result.ongoing and not recent:
            continue

        found = True
        console.print(f"\n[bold]{result.name}[/bold]")
        console.print("-" * 60)

        if result.ongoing:
            console.print(f"\n[red]Ongoing ({len(result.ongoing)})[/red]")
            for incident in result.ongoing:
                console.print(f"  [bold]{incident.name}[/bold]")
                details = [f"Impact: {incident.impact or 'unknown'}"]
                if incident.status:
                    details.append(f"Status: {incident.status}")
                console.print(f"  {' | '.join(details)}")
                console.print(f"  Started: {when(incident.started_at)}")
                if incident.components:
                    console.print(f"  Components: {', '.join(incident.components[:3])}")
                if incident.url:
                    console.print(f"  {incident.url}")
                console.print()

        if recent:
            console.print(f"[yellow]Recent - last {args.days} days ({len(recent)})[/yellow]")
            for incident in recent[:10]:
                console.print(f"  {incident.name}")
                console.print(f"  [dim]{when(incident.resolved_at or incident.started_at)}[/dim]")
            if len(recent) > 10:
                console.print(f"  [dim]... and {len(recent) - 10} more[/dim]")
            console.print()

    if not found:
        if args.show_recent:
            console.print(f"[green]No incidents in the last {args.days} days.[/green]")
        else:
            console.print("[green]No ongoing incidents.[/green]")
            console.print("[dim]Use --show-recent to include resolved incidents.[/dim]")

    blind = [r.name for r in results if not r.supports_history and args.show_recent]
    if blind:
        console.print(f"\n[dim]No incident history published by: {', '.join(blind)}[/dim]")

    return 1 if report_errors(results) else 0


def cmd_maintenance(args) -> int:
    names = [args.provider] if args.provider else None
    results = fetch(names, days=0)

    found = False
    for result in results:
        if not result.maintenance:
            continue

        found = True
        console.print(f"\n[bold]{result.name}[/bold]")
        console.print("-" * 60)

        grouped: dict[str, list] = defaultdict(list)
        for window in result.maintenance:
            grouped[regions.classify(window.name, *window.components)].append(window)

        for region in regions.ORDER:
            windows = grouped.get(region)
            if not windows:
                continue

            active = sum(1 for w in windows if w.in_progress)
            prefix = f"[red]{active} in progress[/red], " if active else ""
            console.print(f"\n[cyan]{region}[/cyan]: {prefix}{len(windows)} scheduled")

            codes = sorted({regions.location_code(w.name) for w in windows})
            console.print(f"  Locations: {', '.join(codes)}")

            dates = sorted({f"{w.scheduled_for:%Y-%m-%d}" for w in windows if w.scheduled_for})
            if dates:
                span = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
                console.print(f"  [dim]Dates: {span}[/dim]")

    if not found:
        console.print("[green]No scheduled maintenance.[/green]")

    blind = [r.name for r in results if not r.supports_maintenance]
    if blind:
        console.print(f"\n[dim]No maintenance calendar published by: {', '.join(blind)}[/dim]")

    return 1 if report_errors(results) else 0


def cmd_providers(args) -> int:
    def mark(supported: bool) -> str:
        return "yes" if supported else DASH

    table = Table(title="Providers", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Source")
    table.add_column("History")
    table.add_column("Maintenance")
    table.add_column("Components")

    for key, provider in sorted(providers.PROVIDERS.items()):
        table.add_row(
            key,
            provider.source,
            mark(provider.supports_history),
            mark(provider.supports_maintenance),
            mark(provider.supports_components),
        )

    console.print(table)
    console.print("\n[dim]Use a name with any command, e.g. 'gwen status cloudflare'.[/dim]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gwen", description="Monitor public cloud status feeds."
    )
    subparsers = parser.add_subparsers(dest="command")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("provider", nargs="?", help="Limit to one provider, e.g. cloudflare")
        return sub

    status = add("status", "Show current status")
    status.add_argument("--days", type=int, default=0, help="Also count incidents from N days back")
    status.set_defaults(func=cmd_status)

    incidents = add("incidents", "Show ongoing and recent incidents")
    incidents.add_argument("--days", type=int, default=14, help="History window (default: 14)")
    incidents.add_argument("--show-recent", action="store_true", help="Include resolved incidents")
    incidents.set_defaults(func=cmd_incidents)

    maintenance = add("maintenance", "Show scheduled maintenance windows")
    maintenance.set_defaults(func=cmd_maintenance)

    listing = subparsers.add_parser("providers", help="List available providers")
    listing.set_defaults(func=cmd_providers)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except KeyError as exc:
        console.print(f"[red]{exc.args[0]}[/red]")
        return 2
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
