"""`gwen watch`: notice when something you depend on changes, and say so once.

Each run fetches the selected providers, reduces each one to a small snapshot
(level, ongoing incidents, degraded components), compares it with the snapshot
saved by the previous run, and sends the differences to a webhook or Telegram. Nothing runs
in the background: schedule it with cron or CI, or pass `--interval`.

Two rules carry over from the rest of the tool:

- An unreadable feed is news, not silence. After `unreadable_after`
  consecutive failed reads it is reported, and again when it recovers. Until
  then the last good snapshot is kept, so one timeout neither pages anyone nor
  makes ongoing incidents look resolved.
- State is only saved after the webhook accepts the message. A failed delivery
  is retried on the next run instead of being lost.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import pathlib
from dataclasses import asdict, dataclass

import aiohttp

from . import providers
from .config import Config
from .providers import CRITICAL, MAJOR, MINOR, OK, SEVERITY, UNKNOWN, ProviderStatus

STATE_VERSION = 1
_WEBHOOK_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)


@dataclass
class Event:
    provider: str
    kind: str
    summary: str
    url: str = ""
    #: What the event is about, without the "new incident:" style prefix.
    title: str = ""
    #: The provider's level after this run, and before it for worse/better.
    level: str = ""
    previous: str = ""


def snapshot(result: ProviderStatus, terms: list[str] | None) -> dict:
    """Reduce a fetch result to what `watch` compares between runs.

    With filter *terms*, only incidents and components naming one of them
    count, and the level is OK unless something relevant is wrong. Components
    are only tracked when filtered: unfiltered, a large provider's list of
    degraded edge locations changes constantly and would bury real news.
    """

    def relevant(*names: str) -> bool:
        if not terms:
            return True
        text = " ".join(names).lower()
        return any(term in text for term in terms)

    incidents = {
        _incident_id(incident): {"name": incident.name, "url": incident.url}
        for incident in result.ongoing
        if relevant(incident.name, *incident.components)
    }
    degraded = (
        {c.name: c.status for c in result.degraded if relevant(c.name)} if terms else {}
    )

    level = result.indicator
    if terms and level not in (OK, UNKNOWN) and not (incidents or degraded):
        level = OK
    if level == OK and incidents:
        level = MINOR

    return {
        "name": result.name,
        "level": level,
        "incidents": incidents,
        "degraded": degraded,
    }


def _incident_id(incident) -> str:
    # AWS links every event to one shared page, so the URL alone is not unique.
    started = incident.started_at.isoformat() if incident.started_at else ""
    return f"{incident.name}|{started}"


def evaluate(
    results: list[tuple[str, ProviderStatus]],
    previous: dict,
    filters: dict[str, list[str]],
    unreadable_after: int,
) -> tuple[list[Event], dict]:
    """Compare this run with *previous* state. Returns events and the new state."""
    events: list[Event] = []
    state: dict = {}

    for key, result in results:
        before = previous.get(key) or {
            "name": result.name,
            "level": OK,
            "incidents": {},
            "degraded": {},
            "failures": 0,
            "unreadable": False,
        }

        if result.error:
            failures = before.get("failures", 0) + 1
            # Keep the last good picture until the feed comes back.
            state[key] = {**before, "failures": failures}
            if failures >= unreadable_after and not before.get("unreadable"):
                state[key]["unreadable"] = True
                events.append(
                    Event(
                        result.name,
                        "unreadable",
                        f"status feed unreadable ({failures} failed reads): {result.error}",
                        title=result.error,
                        level=UNKNOWN,
                    )
                )
            continue

        now = snapshot(result, filters.get(key))
        state[key] = {**now, "failures": 0, "unreadable": False}
        events.extend(_changes(result.name, before, now))

    return events, state


def _changes(name: str, before: dict, now: dict) -> list[Event]:
    """Events for one provider whose feed was read successfully."""
    level = now["level"]
    found: list[Event] = []

    if before.get("unreadable"):
        found.append(Event(name, "readable", "status feed readable again", level=level))

    for ident, incident in now["incidents"].items():
        if ident not in before["incidents"]:
            found.append(
                Event(
                    name,
                    "incident",
                    f"new incident: {incident['name']}",
                    incident["url"],
                    title=incident["name"],
                    level=level,
                )
            )
    for ident, incident in before["incidents"].items():
        if ident not in now["incidents"]:
            found.append(
                Event(
                    name,
                    "resolved",
                    f"no longer listed: {incident['name']}",
                    incident["url"],
                    title=incident["name"],
                    level=level,
                )
            )

    newly = sorted(
        c for c, s in now["degraded"].items() if before["degraded"].get(c) != s
    )
    healed = sorted(c for c in before["degraded"] if c not in now["degraded"])
    if newly:
        found.append(
            Event(
                name,
                "degraded",
                "degraded: " + _names(newly),
                title=_names(newly),
                level=level,
            )
        )
    if healed:
        found.append(
            Event(
                name,
                "recovered",
                "recovered: " + _names(healed),
                title=_names(healed),
                level=level,
            )
        )

    if level != before["level"]:
        worse = SEVERITY[level] > SEVERITY[before["level"]]
        found.append(
            Event(
                name,
                "worse" if worse else "better",
                f"status {before['level']} -> {level}",
                level=level,
                previous=before["level"],
            )
        )
    return found


def _names(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown} and {len(items) - limit} more"


def _count(events: list[Event]) -> str:
    return f"{len(events)} change{'s' if len(events) != 1 else ''}"


def message(events: list[Event]) -> str:
    """Plain text, one line per event: for the console and webhooks."""
    lines = [f"gwen: {_count(events)}"]
    for event in events:
        line = f"- {event.provider}: {event.summary}"
        if event.url:
            line += f" ({event.url})"
        lines.append(line)
    return "\n".join(lines)


DOTS = {OK: "🟢", MINOR: "🟡", MAJOR: "🟠", CRITICAL: "🔴", UNKNOWN: "⚪"}
#: Message order: known outages first, then feeds we cannot see, then good news.
_RANK = {CRITICAL: 4, MAJOR: 3, MINOR: 2, UNKNOWN: 1, OK: 0}
LEVELS = {
    OK: "OK",
    MINOR: "Minor",
    MAJOR: "Major",
    CRITICAL: "Critical",
    UNKNOWN: "Unknown",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _linked(event: Event) -> str:
    title = _esc(event.title)
    return f'<a href="{html.escape(event.url)}">{title}</a>' if event.url else title


def _html_line(event: Event) -> str | None:
    if event.kind == "incident":
        return f"🆕 {_linked(event)}"
    if event.kind == "resolved":
        return f"✅ Resolved: {_linked(event)}"
    if event.kind == "degraded":
        return f"⚠️ Degraded: {_esc(event.title)}"
    if event.kind == "recovered":
        return f"✅ Recovered: {_esc(event.title)}"
    if event.kind == "unreadable":
        return f"❓ Can't read the status feed: <i>{_esc(event.title)}</i>"
    if event.kind == "readable":
        return "📡 Status feed readable again"
    return None  # worse/better are shown in the provider heading


def telegram_html(events: list[Event], limit: int = 4096) -> str:
    """Telegram HTML: one block per provider, worst first, titles as links.

    Lines that would push the message past *limit* are dropped and counted
    rather than cut mid-tag, which Telegram would reject.
    """
    grouped: dict[str, list[Event]] = {}
    for event in events:
        grouped.setdefault(event.provider, []).append(event)
    order = sorted(grouped, key=lambda name: -_RANK.get(grouped[name][0].level, 0))

    blocks: list[list[str]] = []
    for name in order:
        group = grouped[name]
        level = group[0].level or UNKNOWN
        heading = f"{DOTS.get(level, DOTS[UNKNOWN])} <b>{_esc(name)}</b>"
        shift = next((e for e in group if e.kind in ("worse", "better")), None)
        if shift:
            before = LEVELS.get(shift.previous, shift.previous)
            heading += f" · {before} → {LEVELS.get(level, level)}"
        blocks.append([heading] + [line for e in group if (line := _html_line(e))])

    header = f"<b>GWEN</b> · {_count(events)}"
    text = header
    dropped = 0
    for block in blocks:
        for index, line in enumerate(block):
            addition = ("\n\n" if index == 0 else "\n") + line
            # Leave room for the "and N more" note.
            if dropped or len(text) + len(addition) > limit - 40:
                dropped += 1
                continue
            text += addition
    if dropped:
        text += f"\n\n<i>… and {dropped} more line{'s' if dropped != 1 else ''}</i>"
    return text


def payload(events: list[Event]) -> dict:
    """Slack-compatible `text`, plus structured events for anything else."""
    return {"text": message(events), "events": [asdict(event) for event in events]}


class DeliveryError(RuntimeError):
    """A target did not accept the message."""


@dataclass
class Webhook:
    """POST `payload()` as JSON to any URL, e.g. a Slack incoming webhook."""

    url: str
    label = "webhook"

    async def send(self, session: aiohttp.ClientSession, events: list[Event]) -> None:
        async with session.post(self.url, json=payload(events)) as response:
            if response.status >= 400:
                text = (await response.text())[:200]
                raise DeliveryError(f"webhook returned HTTP {response.status}: {text}")


@dataclass
class Telegram:
    """Send the message from a Telegram bot to one chat.

    The token is part of the request URL, so it is scrubbed from every error
    this raises -- otherwise a failed run would print it to a CI log.
    """

    token: str
    chat_id: str
    label = "telegram"
    api: str = "https://api.telegram.org"

    #: Telegram rejects messages longer than this.
    LIMIT = 4096

    async def send(self, session: aiohttp.ClientSession, events: list[Event]) -> None:
        body = {
            "chat_id": self.chat_id,
            "text": telegram_html(events, self.LIMIT),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        try:
            async with session.post(
                f"{self.api}/bot{self.token}/sendMessage", json=body
            ) as response:
                if response.status >= 400:
                    try:
                        reason = (await response.json(content_type=None)).get(
                            "description", ""
                        )
                    except ValueError:
                        reason = ""
                    raise DeliveryError(
                        f"Telegram returned HTTP {response.status}: {reason}"
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise DeliveryError(
                f"Telegram request failed: {str(exc).replace(self.token, '<token>')}"
            ) from None


async def deliver(targets: list, events: list[Event]) -> None:
    """Send *events* to every target. Raises `DeliveryError` if any fails."""
    async with aiohttp.ClientSession(timeout=_WEBHOOK_TIMEOUT) as session:
        for target in targets:
            try:
                await target.send(session, events)
            except DeliveryError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise DeliveryError(
                    f"{target.label} request failed: {exc or 'timed out'}"
                ) from None


def load_state(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Missing is normal on the first run. Corrupt costs one round of
        # repeated alerts, which beats refusing to watch.
        return {}
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return {}
    return data.get("providers") or {}


def save_state(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps({"version": STATE_VERSION, "providers": state}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def selected_keys(config: Config, names: list[str] | None) -> list[str]:
    chosen = names or config.providers or list(providers.PROVIDERS)
    return [providers.resolve(name).key for name in chosen]


async def run_once(
    config: Config,
    keys: list[str],
    state_path: pathlib.Path,
    targets: list,
) -> tuple[list[Event], list[ProviderStatus]]:
    """Fetch, compare, deliver, then save. Raises `DeliveryError` if delivery fails.

    With several targets, one failing means all are retried next run, so the
    others may see a message twice. Duplicates beat a silently lost alert.
    """
    results = await providers.gather(keys, days=0)
    events, state = evaluate(
        list(zip(keys, results)),
        load_state(state_path),
        config.filters,
        config.watch.unreadable_after,
    )
    if events and targets:
        await deliver(targets, events)
    save_state(state_path, state)
    return events, results
