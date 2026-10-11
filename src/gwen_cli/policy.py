"""Decide how loudly each change is announced.

Each `[[watch.rule]]` gives a target -- a provider, or a region of one -- a
priority:

1. Send immediately, at any hour.
2. Send during work hours. Changes outside them are held and sent together
   when work hours next begin, so nothing is silently dropped.
3. Do not send. Recorded in the history only.

Anything no rule covers gets `default_priority` (3 unless configured). An
event's priority is the most urgent of every rule it matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, tzinfo

from . import targets
from .targets import Target

NOTIFY, WORK_HOURS, LOG = 1, 2, 3
PRIORITIES = (NOTIFY, WORK_HOURS, LOG)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class PolicyError(ValueError):
    """A rule or schedule in the config cannot be used."""


@dataclass(frozen=True)
class Rule:
    target: Target
    priority: int
    #: While this target has a problem, these targets are treated as priority 1.
    failover: tuple[Target, ...] = ()


@dataclass(frozen=True)
class Schedule:
    """Weekly work hours, e.g. `Mon-Fri 08:00-18:00`."""

    days: frozenset[int]
    start: time
    end: time
    #: None means the computer's local time zone.
    zone: tzinfo | None = None
    text: str = ""

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.zone)
        return local.weekday() in self.days and self.start <= local.time() < self.end


DEFAULT_HOURS = "Mon-Fri 08:00-18:00"
_HOURS = re.compile(
    r"^\s*([A-Za-z,\- ]+?)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$"
)


def parse_schedule(text: str, zone: str | None = None) -> Schedule:
    """Parse `Mon-Fri 08:00-18:00` (or `Mon,Wed,Fri 09:00-17:00`)."""
    match = _HOURS.match(text)
    if not match:
        raise PolicyError(f"work_hours {text!r} should look like 'Mon-Fri 08:00-18:00'")
    day_spec, h1, m1, h2, m2 = match.groups()
    try:
        start, end = time(int(h1), int(m1)), time(int(h2), int(m2))
    except ValueError:
        raise PolicyError(f"work_hours {text!r} has an invalid time") from None
    if end <= start:
        raise PolicyError(
            f"work_hours {text!r} must end after it starts, on the same day"
        )

    days: set[int] = set()
    for part in day_spec.replace(" ", "").lower().split(","):
        first, _, last = part.partition("-")
        try:
            a = DAYS.index(first[:3])
            b = DAYS.index(last[:3]) if last else a
        except ValueError:
            raise PolicyError(f"work_hours {text!r}: unknown day in {part!r}") from None
        span = range(a, b + 1) if a <= b else [*range(a, 7), *range(0, b + 1)]
        days.update(span)

    return Schedule(frozenset(days), start, end, _zone(zone), text.strip())


def _zone(name: str | None) -> tzinfo | None:
    if not name:
        return None
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise PolicyError(
            f"unknown timezone {name!r}, e.g. 'America/Chicago'"
        ) from None


@dataclass
class Policy:
    rules: list[Rule] = field(default_factory=list)
    default_priority: int = LOG
    hours: Schedule = field(default_factory=lambda: parse_schedule(DEFAULT_HOURS))
    #: True when the config sets `default_priority` itself.
    explicit_default: bool = False

    @property
    def configured(self) -> bool:
        """False with no rules and no default: every change is sent, as before."""
        return bool(self.rules) or self.explicit_default

    def for_provider(self, provider: str) -> list[Rule]:
        return [rule for rule in self.rules if rule.target.provider == provider]

    def classify(
        self,
        provider: str,
        text: str,
        codes: list[str] = (),
        promoted: set[Target] = frozenset(),
    ) -> tuple[int, list[Target]]:
        """Priority of a change to *provider* described by *text* and region *codes*.

        Returns the priority and the configured targets it matched.
        """
        if not self.configured:
            return NOTIFY, []
        matched = [
            rule
            for rule in self.for_provider(provider)
            if targets.matches(rule.target, text, codes)
        ]
        priorities = [rule.priority for rule in matched]
        priorities += [NOTIFY for rule in matched if rule.target in promoted]
        hits = [rule.target for rule in matched]
        # A promoted target with no rule of its own still matches by region.
        for target in promoted:
            if target.provider == provider and target not in hits:
                if targets.matches(target, text, codes):
                    priorities.append(NOTIFY)
                    hits.append(target)
        return (min(priorities) if priorities else self.default_priority), hits

    def provider_wide(self, provider: str, promoted: set[Target] = frozenset()) -> int:
        """Priority of something affecting the whole provider, e.g. its feed going dark."""
        if not self.configured:
            return NOTIFY
        priorities = [rule.priority for rule in self.for_provider(provider)]
        if any(target.provider == provider for target in promoted):
            priorities.append(NOTIFY)
        return min(priorities) if priorities else self.default_priority

    def provider_level(self, provider: str) -> int:
        """Priority from a rule naming the provider without a region, else the default."""
        if not self.configured:
            return NOTIFY
        priorities = [
            rule.priority
            for rule in self.for_provider(provider)
            if rule.target.region is None
        ]
        return min(priorities) if priorities else self.default_priority

    def component_terms(self, provider: str) -> list[str]:
        """Region names to track degraded components for, on catalog-less providers."""
        if provider in targets.CATALOGS:
            return []
        return [
            rule.target.region
            for rule in self.for_provider(provider)
            if rule.target.region
        ]


def parse_rules(entries: list[dict]) -> list[Rule]:
    rules = []
    for entry in entries:
        if not isinstance(entry, dict) or "target" not in entry:
            raise PolicyError(
                'each [[watch.rule]] needs a target, e.g. target = "azure/scus"'
            )
        try:
            target = targets.parse(str(entry["target"]))
            failover = tuple(
                targets.parse(str(spec)) for spec in entry.get("failover", [])
            )
        except targets.TargetError as exc:
            raise PolicyError(str(exc)) from None
        priority = entry.get("priority", LOG)
        if priority not in PRIORITIES or isinstance(priority, bool):
            raise PolicyError(f"rule {target}: priority must be 1, 2 or 3")
        if failover and priority != NOTIFY:
            raise PolicyError(
                f"rule {target}: failover only applies to priority 1 targets"
            )
        rules.append(Rule(target, priority, failover))
    return rules
