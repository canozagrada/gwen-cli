"""`gwen watch`: notice when something you depend on changes, and say so once.

Each run fetches the selected providers, reduces each one to a small snapshot
(level, ongoing incidents, degraded components), compares it with the snapshot
saved by the previous run, and routes each difference by priority (see
`policy`): sent now, held for work hours, or only recorded in the history.
Nothing runs in the background: schedule it with cron or CI, or pass
`--interval`.

Two rules carry over from the rest of the tool:

- An unreadable feed is news, not silence. After `unreadable_after`
  consecutive failed reads it is reported, and again when it recovers. Until
  then the last good snapshot is kept, so one timeout neither pages anyone nor
  makes ongoing incidents look resolved.
- State and history are only saved after every target accepts the message.
  A failed delivery is retried on the next run instead of being lost.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import pathlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import aiohttp

from . import history, providers, targets
from .config import Config
from .policy import NOTIFY, WORK_HOURS, Policy
from .providers import CRITICAL, MAJOR, MINOR, OK, SEVERITY, UNKNOWN, ProviderStatus

STATE_VERSION = 1
#: State key holding the failover targets currently promoted to priority 1.
#: Provider keys never start with an underscore.
FAILOVER = "_failover"
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
    #: Provider key, e.g. "azure".
    key: str = ""
    #: 1 send now, 2 send in work hours, 3 history only. See `policy`.
    priority: int = NOTIFY
    #: Configured targets this change matched, e.g. ["azure/southcentralus"].
    targets: list[str] = field(default_factory=list)
    #: Region codes the provider attached to the incident.
    regions: list[str] = field(default_factory=list)
    #: Lowercase text that targets are matched against.
    text: str = ""
    #: When gwen first saw it (ISO 8601); set on changes released from hold.
    seen: str = ""


def snapshot(
    result: ProviderStatus, terms: list[str] | None, component_terms: list[str] = ()
) -> dict:
    """Reduce a fetch result to what `watch` compares between runs.

    With filter *terms*, only incidents and components naming one of them
    count, and the level is OK unless something relevant is wrong. Components
    are only tracked when they match a filter or a rule's region
    (*component_terms*): unfiltered, a large provider's list of degraded edge
    locations changes constantly and would bury real news.
    """

    def relevant(*names: str) -> bool:
        if not terms:
            return True
        text = " ".join(names).lower()
        return any(term in text for term in terms)

    def watched(name: str) -> bool:
        if terms and relevant(name):
            return True
        return any(targets.names(term, name) for term in component_terms)

    incidents = {
        _incident_id(incident): {
            "name": incident.name,
            "url": incident.url,
            "text": " ".join(
                [incident.name, *incident.components, *incident.regions]
            ).lower(),
            "regions": list(incident.regions),
        }
        for incident in result.ongoing
        if relevant(incident.name, *incident.components)
    }
    degraded = {c.name: c.status for c in result.degraded if watched(c.name)}

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
    policy: Policy | None = None,
) -> tuple[list[Event], dict]:
    """Compare this run with *previous* state. Returns events and the new state.

    Every event carries a priority from *policy*; without one, everything is
    priority 1, as before rules existed.
    """
    policy = policy or Policy()
    raw: list[Event] = []
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
                raw.append(
                    Event(
                        result.name,
                        "unreadable",
                        f"status feed unreadable ({failures} failed reads): {result.error}",
                        title=result.error,
                        level=UNKNOWN,
                        key=key,
                    )
                )
            continue

        now = snapshot(result, filters.get(key), policy.component_terms(key))
        state[key] = {**now, "failures": 0, "unreadable": False}
        raw.extend(_changes(key, result.name, before, now))

    promoted = promotions(policy, state)
    was = {targets.parse(spec) for spec in previous.get(FAILOVER, []) if _known(spec)}
    if promoted:
        state[FAILOVER] = sorted(str(target) for target in promoted)

    events = _prioritise(raw, policy, promoted)
    events += _failover_changes(policy, state, was, promoted)
    return events, state


def _known(spec: str) -> bool:
    try:
        targets.parse(spec)
    except targets.TargetError:
        return False
    return True


def _changes(key: str, name: str, before: dict, now: dict) -> list[Event]:
    """Events for one provider whose feed was read successfully.

    Components get one event each here; `_prioritise` merges them again once
    each has a priority.
    """
    level = now["level"]
    found: list[Event] = []

    def event(kind, summary, **fields):
        found.append(Event(name, kind, summary, level=level, key=key, **fields))

    if before.get("unreadable"):
        event("readable", "status feed readable again")

    for ident, incident in now["incidents"].items():
        if ident not in before["incidents"]:
            event(
                "incident",
                f"new incident: {incident['name']}",
                url=incident["url"],
                title=incident["name"],
                text=incident.get("text", incident["name"].lower()),
                regions=incident.get("regions", []),
            )
    for ident, incident in before["incidents"].items():
        if ident not in now["incidents"]:
            event(
                "resolved",
                f"no longer listed: {incident['name']}",
                url=incident["url"],
                title=incident["name"],
                text=incident.get("text", incident["name"].lower()),
                regions=incident.get("regions", []),
            )

    for component, status in sorted(now["degraded"].items()):
        if before["degraded"].get(component) != status:
            event(
                "degraded",
                f"degraded: {component}",
                title=component,
                text=component.lower(),
            )
    for component in sorted(before["degraded"]):
        if component not in now["degraded"]:
            event(
                "recovered",
                f"recovered: {component}",
                title=component,
                text=component.lower(),
            )

    if level != before["level"]:
        worse = SEVERITY[level] > SEVERITY[before["level"]]
        event(
            "worse" if worse else "better",
            f"status {before['level']} -> {level}",
            previous=before["level"],
        )
    return found


def _prioritise(raw: list[Event], policy: Policy, promoted: set) -> list[Event]:
    for event in raw:
        if event.kind in ("incident", "resolved", "degraded", "recovered"):
            event.priority, matched = policy.classify(
                event.key, event.text, event.regions, promoted
            )
            event.targets = [str(target) for target in matched]
        elif event.kind in ("unreadable", "readable"):
            # A feed going dark hides every region of it, so it is as urgent
            # as the most urgent thing you watch there.
            event.priority = policy.provider_wide(event.key, promoted)

    for event in raw:
        if event.kind in ("worse", "better"):
            # As urgent as the change that caused it; otherwise the provider's own rule.
            related = [e.priority for e in raw if e.key == event.key and e is not event]
            event.priority = (
                min(related) if related else policy.provider_level(event.key)
            )

    return _merge_components(raw)


def _merge_components(events: list[Event]) -> list[Event]:
    """Fold per-component events back into one per provider, kind and priority."""
    merged: list[Event] = []
    groups: dict[tuple, list[Event]] = {}
    for event in events:
        if event.kind not in ("degraded", "recovered"):
            merged.append(event)
            continue
        group_key = (event.key, event.kind, event.priority)
        if group_key not in groups:
            groups[group_key] = []
            merged.append(event)  # placeholder, replaced below
        groups[group_key].append(event)

    for index, event in enumerate(merged):
        group = groups.get((event.key, event.kind, event.priority))
        if event.kind in ("degraded", "recovered") and group and group[0] is event:
            names = _names([e.title for e in group])
            merged[index] = Event(
                event.provider,
                event.kind,
                f"{event.kind}: {names}",
                title=names,
                level=event.level,
                key=event.key,
                priority=event.priority,
                targets=sorted({t for e in group for t in e.targets}),
                text=" ".join(e.text for e in group),
            )
    return merged


def promotions(policy: Policy, state: dict) -> set:
    """Failover targets of every priority-1 target that currently has a problem."""
    promoted = set()
    for rule in policy.rules:
        if not rule.failover:
            continue
        current = state.get(rule.target.provider)
        if current and _affected(rule.target, current):
            promoted.update(rule.failover)
    return promoted


def _affected(target: targets.Target, current: dict) -> bool:
    for incident in current.get("incidents", {}).values():
        text = incident.get("text", incident["name"].lower())
        if targets.matches(target, text, incident.get("regions", [])):
            return True
    return any(
        targets.matches(target, name.lower()) for name in current.get("degraded", {})
    )


def _failover_changes(policy: Policy, state: dict, was: set, now: set) -> list[Event]:
    events = []
    for target in sorted(now - was, key=str):
        primaries = [str(r.target) for r in policy.rules if target in r.failover]
        events.append(_failover_event(state, target, "failover", primaries))
    for target in sorted(was - now, key=str):
        events.append(_failover_event(state, target, "failover-end", []))
    return events


def _failover_event(state, target, kind, primaries) -> Event:
    label = providers.PROVIDERS[target.provider].label
    current = state.get(target.provider, {})
    if kind == "failover":
        because = ", ".join(primaries)
        summary = f"{target} is now priority 1 while {because} has problems"
    else:
        summary = f"{target} back to its normal priority"
    return Event(
        label,
        kind,
        summary,
        title=summary,
        level=current.get("level", OK),
        key=target.provider,
        priority=NOTIFY,
        targets=[str(target)],
    )


def _names(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown} and {len(items) - limit} more"


def _count(events: list[Event]) -> str:
    return f"{len(events)} change{'s' if len(events) != 1 else ''}"


# --- routing ----------------------------------------------------------------


def route(events: list[Event], in_hours: bool) -> list[tuple[Event, str]]:
    """Pair each event with `history.NOTIFY`, `HOLD` or `LOG`."""
    routed = []
    for event in events:
        if event.priority == NOTIFY or (event.priority == WORK_HOURS and in_hours):
            routed.append((event, history.NOTIFY))
        elif event.priority == WORK_HOURS:
            routed.append((event, history.HOLD))
        else:
            routed.append((event, history.LOG))
    return routed


def from_history(fields: dict) -> Event:
    names = {name for name in Event.__dataclass_fields__}
    event = Event(**{k: v for k, v in fields.items() if k in names and k != "seen"})
    event.seen = fields["at"].isoformat()
    return event


# --- rendering --------------------------------------------------------------


def _line(event: Event) -> str:
    line = f"- {event.provider}: {event.summary}"
    if event.url:
        line += f" ({event.url})"
    if event.targets and event.kind not in ("failover", "failover-end"):
        line += f" [{', '.join(event.targets)}]"
    return line


def message(events: list[Event], held: list[Event] = ()) -> str:
    """Plain text, one line per event: for the console and webhooks."""
    lines = [f"gwen: {_count(events)}"] if events else []
    lines += [_line(event) for event in events]
    if held:
        if lines:
            lines.append("")
        lines.append(f"While you were away: {_count(held)}")
        lines += [_line(event) for event in held]
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


def _why(event: Event) -> str:
    """Which of your targets this is about, e.g. ` · azure/southcentralus`."""
    if not event.targets:
        return ""
    return f" · <i>{_esc(', '.join(event.targets))}</i>"


def _html_line(event: Event) -> str | None:
    if event.kind == "incident":
        return f"🆕 {_linked(event)}{_why(event)}"
    if event.kind == "resolved":
        return f"✅ Resolved: {_linked(event)}{_why(event)}"
    if event.kind == "degraded":
        return f"⚠️ Degraded: {_esc(event.title)}{_why(event)}"
    if event.kind == "recovered":
        return f"✅ Recovered: {_esc(event.title)}{_why(event)}"
    if event.kind == "unreadable":
        return f"❓ Can't read the status feed: <i>{_esc(event.title)}</i>"
    if event.kind == "readable":
        return "📡 Status feed readable again"
    if event.kind == "failover":
        return f"⬆️ {_esc(event.title)}"
    if event.kind == "failover-end":
        return f"⬇️ {_esc(event.title)}"
    return None  # worse/better are shown in the provider heading


def _html_blocks(events: list[Event]) -> list[list[str]]:
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
    return blocks


def _since(held: list[Event]) -> str:
    first = min((e.seen for e in held if e.seen), default="")
    if not first:
        return ""
    moment = datetime.fromisoformat(first).astimezone()
    return f" since {moment:%a %H:%M}"


def telegram_html(
    events: list[Event], limit: int = 4096, held: list[Event] = ()
) -> str:
    """Telegram HTML: one block per provider, worst first, titles as links.

    Changes held outside work hours follow under "While you were away". Lines
    that would push the message past *limit* are dropped and counted rather
    than cut mid-tag, which Telegram would reject.
    """
    sections: list[tuple[str, list[list[str]]]] = []
    if events:
        sections.append((f"<b>GWEN</b> · {_count(events)}", _html_blocks(events)))
    if held:
        title = f"<b>While you were away</b> · {_count(held)}{_esc(_since(held))}"
        if not events:
            title = (
                f"<b>GWEN</b> · {_count(held)} while you were away{_esc(_since(held))}"
            )
        sections.append((title, _html_blocks(held)))

    text = ""
    dropped = 0
    for title, blocks in sections:
        lines = [(title, "\n\n" if text else "")]
        for block in blocks:
            lines += [
                (line, "\n\n" if index == 0 else "\n")
                for index, line in enumerate(block)
            ]
        for line, gap in lines:
            # Leave room for the "and N more" note.
            if dropped or len(text) + len(gap) + len(line) > limit - 40:
                dropped += 1
                continue
            text += gap + line
    if dropped:
        text += f"\n\n<i>… and {dropped} more line{'s' if dropped != 1 else ''}</i>"
    return text


def payload(events: list[Event], held: list[Event] = ()) -> dict:
    """Slack-compatible `text`, plus structured events for anything else."""
    return {
        "text": message(events, held),
        "events": [asdict(event) for event in events],
        "held": [asdict(event) for event in held],
    }


# --- delivery ---------------------------------------------------------------


class DeliveryError(RuntimeError):
    """A target did not accept the message."""


@dataclass
class Webhook:
    """POST `payload()` as JSON to any URL, e.g. a Slack incoming webhook."""

    url: str
    label = "webhook"

    async def send(
        self,
        session: aiohttp.ClientSession,
        events: list[Event],
        held: list[Event] = (),
    ) -> None:
        async with session.post(self.url, json=payload(events, held)) as response:
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

    async def send(
        self,
        session: aiohttp.ClientSession,
        events: list[Event],
        held: list[Event] = (),
    ) -> None:
        body = {
            "chat_id": self.chat_id,
            "text": telegram_html(events, self.LIMIT, held),
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


async def deliver(targets: list, events: list[Event], held: list[Event] = ()) -> None:
    """Send to every target. Raises `DeliveryError` if any fails."""
    async with aiohttp.ClientSession(timeout=_WEBHOOK_TIMEOUT) as session:
        for target in targets:
            try:
                await target.send(session, events, held)
            except DeliveryError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise DeliveryError(
                    f"{target.label} request failed: {exc or 'timed out'}"
                ) from None


# --- state ------------------------------------------------------------------


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


def history_path(
    config: Config, state_path: pathlib.Path | None = None
) -> pathlib.Path:
    """`[watch] history`, or `.gwen-history.sqlite` beside the state file."""
    if config.watch.history:
        return config.watch.history
    return (state_path or config.watch.state).with_name(".gwen-history.sqlite")


def selected_keys(config: Config, names: list[str] | None) -> list[str]:
    chosen = names or config.providers or list(providers.PROVIDERS)
    return [providers.resolve(name).key for name in chosen]


@dataclass
class Run:
    routed: list[tuple[Event, str]]
    released: list[Event]
    results: list[ProviderStatus]
    in_hours: bool

    @property
    def events(self) -> list[Event]:
        return [event for event, _ in self.routed]

    def sent(self) -> list[Event]:
        return [event for event, way in self.routed if way == history.NOTIFY]


async def run_once(
    config: Config,
    keys: list[str],
    state_path: pathlib.Path,
    targets: list,
    now: datetime | None = None,
) -> Run:
    """Fetch, compare, route, deliver, then record. Raises `DeliveryError`.

    With several targets, one failing means all are retried next run, so the
    others may see a message twice. Duplicates beat a silently lost alert.
    With no targets (a dry run) nothing is sent and held changes stay held.
    """
    now = now or datetime.now(timezone.utc)
    policy = config.watch.policy
    results = await providers.gather(keys, days=0)
    events, state = evaluate(
        list(zip(keys, results)),
        load_state(state_path),
        config.filters,
        config.watch.unreadable_after,
        policy,
    )

    log = history_path(config, state_path)
    in_hours = policy.hours.contains(now)
    routed = route(events, in_hours)
    waiting = history.held(log) if in_hours else []
    released = [from_history(fields) for _, fields in waiting]
    to_send = [event for event, way in routed if way == history.NOTIFY]

    if targets and (to_send or released):
        await deliver(targets, to_send, released)

    history.record(
        log,
        routed,
        now,
        release=[row_id for row_id, _ in waiting] if targets else [],
    )
    save_state(state_path, state)
    return Run(routed, released, results, in_hours)
