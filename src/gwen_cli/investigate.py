"""`gwen investigate`: what else was going on around a problem with a target?

Reads the history, finds the target's most recent problem (or a time you
give), and sorts everything recorded around it by how it relates:

- `target`: the target itself
- `failover`: a region its load fails over to, from its rule
- `provider`: other regions of the same provider
- `area`: other providers in the same part of the world
- `other`: everything else in the window

No guessing beyond that: the point is to put related changes -- including
priority-3 ones nobody was alerted about -- side by side, in time order.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import history, regions, targets
from .policy import Policy
from .targets import Target

TARGET, FAILOVER, PROVIDER, AREA, OTHER = (
    "target",
    "failover",
    "provider",
    "area",
    "other",
)
RELATIONS = (TARGET, FAILOVER, PROVIDER, AREA, OTHER)

#: Kinds that mark something going wrong, used to find the anchor.
PROBLEMS = ("incident", "degraded", "unreadable", "worse")


@dataclass
class Finding:
    row: dict
    relation: str
    offset: timedelta


def parse_window(text: str) -> timedelta:
    """`2h`, `90m`, `1d` -> timedelta."""
    match = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", text.lower())
    if not match:
        raise ValueError(f"window {text!r} should look like 90m, 2h or 1d")
    unit = {"m": "minutes", "h": "hours", "d": "days"}[match.group(2)]
    return timedelta(**{unit: int(match.group(1))})


def parse_moment(text: str) -> datetime:
    """`2026-10-11 14:00` in local time, or any ISO 8601 timestamp."""
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"time {text!r} should look like '2026-10-11 14:00'") from None
    return moment if moment.tzinfo else moment.astimezone()


def about(row: dict, target: Target) -> bool:
    """Is a recorded change about *target*?"""
    if row["key"] != target.provider:
        return False
    if str(target) in row["targets"]:
        return True
    return targets.matches(target, row["text"] or row["title"].lower(), row["regions"])


def anchor(path: pathlib.Path, target: Target) -> dict | None:
    """The target's most recent recorded problem."""
    for row in history.latest(path, target.provider, PROBLEMS):
        if about(row, target):
            return row
    return None


def _geo(row: dict) -> str | None:
    found = targets.mentioned(row["key"], row["text"] or row["title"], row["regions"])
    if found:
        geos = {targets.CATALOGS[row["key"]][code].geo for code in found}
        return geos.pop() if len(geos) == 1 else None
    if found is None:
        geo = regions.classify(row["title"], row["text"])
        return None if geo == regions.OTHER else geo
    return None  # names no region: could be anywhere


def _target_geo(target: Target) -> str | None:
    if target.geo:
        return target.geo
    if target.region:
        geo = regions.classify(target.region)
        return None if geo == regions.OTHER else geo
    return None


def relate(row: dict, target: Target, failover: tuple[Target, ...]) -> str:
    if about(row, target):
        return TARGET
    if any(about(row, other) for other in failover):
        return FAILOVER
    if row["key"] == target.provider:
        return PROVIDER
    area = _target_geo(target)
    if area and _geo(row) == area:
        return AREA
    return OTHER


def investigate(
    path: pathlib.Path,
    target: Target,
    policy: Policy,
    at: datetime | None = None,
    window: timedelta = timedelta(hours=2),
) -> tuple[datetime | None, list[Finding]]:
    """Changes within *window* either side of *at* (default: the target's last problem)."""
    if at is None:
        found = anchor(path, target)
        if found is None:
            return None, []
        at = found["at"]

    failover = tuple(
        other
        for rule in policy.rules
        if rule.target == target
        for other in rule.failover
    )
    rows = history.between(path, at - window, at + window)
    return at, [
        Finding(row, relate(row, target, failover), row["at"] - at) for row in rows
    ]
