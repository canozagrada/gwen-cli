"""GWEN - a command-line monitor for public cloud status feeds."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import pathlib
import time
from collections import defaultdict
from datetime import datetime

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import (
    config,
    history,
    investigate,
    providers,
    regions,
    targets,
    telegram_setup,
    watch,
)
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
    names = [args.provider] if args.provider else args.config.providers
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
    names = [args.provider] if args.provider else args.config.providers
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
    names = [args.provider] if args.provider else args.config.providers
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


def watch_targets(args) -> list:
    """Build delivery targets from flags, environment and config.

    Secrets (the webhook URL, the bot token) can come from the environment so
    they stay out of shell history and committed config.
    """
    settings = args.config.watch
    targets: list = []

    webhook = args.webhook or os.environ.get("GWEN_WEBHOOK") or settings.webhook
    if webhook:
        if not webhook.startswith(("https://", "http://")):
            raise ValueError("Webhook must be an http(s) URL.")
        targets.append(watch.Webhook(webhook))

    token = os.environ.get("GWEN_TELEGRAM_TOKEN")
    chat = args.telegram_chat or os.environ.get("GWEN_TELEGRAM_CHAT") or settings.telegram_chat
    if token and chat:
        targets.append(watch.Telegram(token, chat))
    elif token or chat:
        raise ValueError(
            "Telegram needs both GWEN_TELEGRAM_TOKEN and a chat "
            "(--telegram-chat, GWEN_TELEGRAM_CHAT or [watch] telegram_chat)."
        )
    return targets


def cmd_watch(args) -> int:
    try:
        targets = [] if args.dry_run else watch_targets(args)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    if not targets and not args.dry_run:
        console.print(
            "[red]Nowhere to send changes: set GWEN_WEBHOOK or GWEN_TELEGRAM_TOKEN "
            "(see 'gwen watch --help'), or use --dry-run.[/red]"
        )
        return 2

    keys = watch.selected_keys(args.config, [args.provider] if args.provider else None)
    state_path = args.state or args.config.watch.state

    while True:
        try:
            run = asyncio.run(watch.run_once(args.config, keys, state_path, targets))
        except watch.DeliveryError as exc:
            # State was not saved, so the same changes are sent next run.
            console.print(f"[red]Delivery failed: {escape(str(exc))}[/red]")
            code = 3
        else:
            show_run(run, args.dry_run)
            code = 1 if report_errors(run.results) else 0

        if not args.interval:
            return code
        time.sleep(args.interval)


def show_run(run, dry_run: bool) -> None:
    """Print what changed and where each change went."""
    if not run.routed and not run.released:
        console.print("[dim]No changes.[/dim]")
        return

    sent = "Would send" if dry_run else "Sent"
    sections = [
        (f"{sent} now", [e for e, way in run.routed if way == history.NOTIFY]),
        ("Held for work hours", [e for e, way in run.routed if way == history.HOLD]),
        ("History only (priority 3)", [e for e, way in run.routed if way == history.LOG]),
        (f"{sent}: held from earlier", run.released if not dry_run or run.in_hours else []),
    ]
    for title, events in sections:
        if not events:
            continue
        console.print(f"[bold]{title}[/bold] ({len(events)})")
        for event in events:
            console.print(escape(watch._line(event)))
    if dry_run:
        console.print("[dim]Dry run: nothing was sent; held changes stay held.[/dim]")


RELATION_STYLE = {
    investigate.TARGET: "bold red",
    investigate.FAILOVER: "bold yellow",
    investigate.PROVIDER: "yellow",
    investigate.AREA: "cyan",
    investigate.OTHER: "dim",
}


def _offset(delta) -> str:
    minutes = round(delta.total_seconds() / 60)
    sign = "-" if minutes < 0 else "+"
    hours, minutes = divmod(abs(minutes), 60)
    return f"{sign}{hours}h{minutes:02d}m" if hours else f"{sign}{minutes}m"


def cmd_investigate(args) -> int:
    try:
        target = targets.parse(args.target)
        window = investigate.parse_window(args.window)
        at = investigate.parse_moment(args.at) if args.at else None
    except ValueError as exc:  # TargetError is a ValueError
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 2

    path = watch.history_path(args.config, args.state)
    if not path.exists():
        console.print(
            f"[yellow]No history at {escape(str(path))} yet.[/yellow] "
            "'gwen watch' records it; run that on a schedule first."
        )
        return 0

    moment, findings = investigate.investigate(path, target, args.config.watch.policy, at, window)
    if moment is None:
        console.print(f"No recorded problems for {target} in {escape(str(path))}.")
        console.print("[dim]Pass --at '2026-10-11 14:00' to look around a time instead.[/dim]")
        return 0

    local = moment.astimezone()
    console.print(
        f"\n[bold]{target}[/bold] around {local:%a %Y-%m-%d %H:%M} "
        f"(±{args.window}): {len(findings)} recorded change{'s' if len(findings) != 1 else ''}"
    )
    if not findings:
        return 0

    table = Table(box=box.ROUNDED)
    table.add_column("When", no_wrap=True)
    table.add_column("", justify="right", style="dim", no_wrap=True)
    table.add_column("P", justify="center")
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Change")
    table.add_column("Related as", no_wrap=True)
    for finding in findings:
        row = finding.row
        style = RELATION_STYLE[finding.relation]
        table.add_row(
            f"{row['at'].astimezone():%a %H:%M}",
            _offset(finding.offset),
            str(row["priority"]),
            escape(row["provider"]),
            escape(row["summary"]),
            f"[{style}]{finding.relation}[/{style}]",
        )
    console.print(table)

    counts = {r: sum(1 for f in findings if f.relation == r) for r in investigate.RELATIONS}
    console.print(
        "[dim]"
        + ", ".join(f"{n} {r}" for r, n in counts.items() if n)
        + "[/dim]"
    )
    quiet = [
        f for f in findings
        if f.row["route"] == history.LOG and f.relation != investigate.OTHER
    ]
    if quiet:
        console.print(
            f"[yellow]{len(quiet)} related change{'s were' if len(quiet) != 1 else ' was'} "
            "priority 3 and not sent at the time.[/yellow]"
        )
    return 0


BOTFATHER_STEPS = """\
[bold]Connect GWEN to Telegram[/bold]

You need a Telegram bot for GWEN to message you from. If you don't have one yet:
  1. Open [link=https://t.me/BotFather]https://t.me/BotFather[/link] and send [bold]/newbot[/bold]
  2. Pick any name, then a username ending in "bot"
  3. BotFather replies with a token like [dim]123456789:AAH...[/dim]; copy it
"""


def _ask_token() -> str | None:
    console.print(BOTFATHER_STEPS)
    for _ in range(3):
        token = getpass.getpass("Paste the bot token (it won't be shown): ").strip()
        if telegram_setup.looks_like_token(token):
            return token
        console.print("[yellow]That doesn't look like a bot token (digits, a colon, then letters). Try again.[/yellow]")
    return None


def cmd_setup(args) -> int:
    existing = os.environ.get(telegram_setup.TOKEN_VAR, "")
    if existing and not args.new_token and telegram_setup.looks_like_token(existing):
        console.print(f"Using the bot token already saved in {telegram_setup.TOKEN_VAR}. "
                      "[dim](--new-token to use a different bot)[/dim]")
        token = existing
    else:
        token = _ask_token()
        if token is None:
            return 2

    def choose(chats):
        console.print("\nSeveral chats have messaged the bot. Which one should GWEN use?")
        for number, chat in enumerate(chats, 1):
            console.print(f"  {number}. {escape(chat.name)} [dim]({chat.kind})[/dim]")
        while True:
            answer = input(f"Number (1-{len(chats)}): ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(chats):
                return chats[int(answer) - 1]

    try:
        username, chat = asyncio.run(
            telegram_setup.connect(token, lambda line: console.print(escape(line)), choose)
        )
    except telegram_setup.SetupError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1

    where = telegram_setup.save(token, chat.id)
    console.print(f"\n[green]Connected.[/green] Sent a test message to {escape(chat.name)} via @{username}.")
    if where:
        console.print(f"Saved the token and chat id to {where}.")
        console.print("[dim]'gwen watch' and scheduled tasks started from now on will use them.[/dim]")
    else:
        console.print("Add these to the environment that runs 'gwen watch' (e.g. your crontab):")
        console.print(f"  {telegram_setup.TOKEN_VAR}=<the token you pasted>")
        console.print(f"  {telegram_setup.CHAT_VAR}={chat.id}")
    console.print("Try it: [bold]gwen watch --dry-run[/bold], then [bold]gwen watch[/bold].")
    return 0


def cmd_regions(args) -> int:
    if not args.provider:
        console.print("Region lists are built in for: " + ", ".join(sorted(targets.CATALOGS)))
        console.print(
            "[dim]Other providers match a region as a word in incident and component names, "
            "e.g. cloudflare/dfw. Run 'gwen regions azure' for a list.[/dim]"
        )
        return 0

    key = providers.resolve(args.provider).key
    catalog = targets.CATALOGS.get(key)
    if catalog is None:
        console.print(
            f"{providers.PROVIDERS[key].label} has no built-in region list. A target such as "
            f"{key}/dfw matches 'dfw' as a whole word in incident and component names."
        )
        return 0

    table = Table(title=f"{providers.PROVIDERS[key].label} regions", box=box.ROUNDED)
    table.add_column("Target", style="cyan", no_wrap=True)
    table.add_column("Also accepted")
    table.add_column("Geography")
    if key == "azure":
        table.add_column("Paired with")
    for region in catalog.values():
        names = [n for n in (*region.aliases, *region.names) if n != region.code]
        cells = [f"{key}/{region.code}", ", ".join(names), region.geo]
        if key == "azure":
            cells.append(region.pair or "")
        table.add_row(*cells)
    console.print(table)
    if key == "azure":
        console.print("[dim]Paired regions are natural failover targets.[/dim]")
    return 0


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


def _interval(value: str) -> int:
    seconds = int(value)
    if seconds and seconds < 60:
        raise argparse.ArgumentTypeError("must be at least 60 seconds")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gwen", description="Monitor public cloud status feeds."
    )
    parser.add_argument(
        "--config", type=pathlib.Path, help="Config file (default: ./gwen.toml if present)"
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

    watching = add("watch", "Send status changes to a webhook or Telegram")
    watching.add_argument("--webhook", help="URL to POST changes to (or set GWEN_WEBHOOK)")
    watching.add_argument(
        "--telegram-chat",
        help="Telegram chat id to message; the bot token comes from GWEN_TELEGRAM_TOKEN",
    )
    watching.add_argument(
        "--state", type=pathlib.Path, help="State file (default: .gwen-state.json)"
    )
    watching.add_argument(
        "--interval", type=_interval, default=0,
        help="Keep running, checking every N seconds (minimum 60). Default: run once",
    )
    watching.add_argument(
        "--dry-run", action="store_true", help="Print changes instead of sending them"
    )
    watching.set_defaults(func=cmd_watch)

    looking = subparsers.add_parser(
        "investigate", help="Show recorded changes around a target's last problem"
    )
    looking.add_argument("target", help="e.g. azure/scus, aws/us-east-1, github")
    looking.add_argument("--at", help="Look around this time instead, e.g. '2026-10-11 14:00'")
    looking.add_argument("--window", default="2h", help="How far either side (default: 2h)")
    looking.add_argument(
        "--state", type=pathlib.Path, help="State file the history sits beside"
    )
    looking.set_defaults(func=cmd_investigate)

    listing_regions = subparsers.add_parser("regions", help="List region names for targets")
    listing_regions.add_argument("provider", nargs="?", help="e.g. azure")
    listing_regions.set_defaults(func=cmd_regions)

    setup = subparsers.add_parser("setup", help="Connect a notification channel")
    setup.add_argument("channel", choices=["telegram"], help="What to connect")
    setup.add_argument(
        "--new-token", action="store_true", help="Ask for a token even if one is saved"
    )
    setup.set_defaults(func=cmd_setup)

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
        args.config = config.load(args.config)
    except config.ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

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
