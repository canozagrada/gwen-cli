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
import json
import os
import pathlib
from dataclasses import asdict, dataclass

import aiohttp

from . import providers
from .config import Config
from .providers import MINOR, OK, SEVERITY, UNKNOWN, ProviderStatus

STATE_VERSION = 1
_WEBHOOK_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)


@dataclass
class Event:
    provider: str
    kind: str
    summary: str
    url: str = ""


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
                    )
                )
            continue

        now = snapshot(result, filters.get(key))
        state[key] = {**now, "failures": 0, "unreadable": False}

        if before.get("unreadable"):
            events.append(Event(result.name, "readable", "status feed readable again"))

        for ident, incident in now["incidents"].items():
            if ident not in before["incidents"]:
                events.append(
                    Event(
                        result.name,
                        "incident",
                        f"new incident: {incident['name']}",
                        incident["url"],
                    )
                )
        for ident, incident in before["incidents"].items():
            if ident not in now["incidents"]:
                events.append(
                    Event(
                        result.name,
                        "resolved",
                        f"no longer listed: {incident['name']}",
                        incident["url"],
                    )
                )

        newly = sorted(
            c for c, s in now["degraded"].items() if before["degraded"].get(c) != s
        )
        healed = sorted(c for c in before["degraded"] if c not in now["degraded"])
        if newly:
            events.append(Event(result.name, "degraded", "degraded: " + _names(newly)))
        if healed:
            events.append(
                Event(result.name, "recovered", "recovered: " + _names(healed))
            )

        if now["level"] != before["level"]:
            worse = SEVERITY[now["level"]] > SEVERITY[before["level"]]
            events.append(
                Event(
                    result.name,
                    "worse" if worse else "better",
                    f"status {before['level']} -> {now['level']}",
                )
            )

    return events, state


def _names(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown} and {len(items) - limit} more"


def message(events: list[Event]) -> str:
    lines = [f"gwen: {len(events)} change{'s' if len(events) != 1 else ''}"]
    for event in events:
        line = f"- {event.provider}: {event.summary}"
        if event.url:
            line += f" ({event.url})"
        lines.append(line)
    return "\n".join(lines)


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
        text = message(events)
        if len(text) > self.LIMIT:
            text = text[: self.LIMIT - 30].rsplit("\n", 1)[0] + "\n... (truncated)"
        body = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
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
