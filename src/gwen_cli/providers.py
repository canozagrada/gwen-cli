"""Fetch operational status from public cloud provider status feeds.

Every provider is normalised into the same `ProviderStatus` shape so the CLI
never needs to know how a given vendor publishes its data.

Providers differ in what they actually expose. Where a provider cannot supply
something -- Azure publishes no incident history, AWS and GCP publish no
maintenance calendar -- it says so via `supports_*` rather than returning an
empty list. A status tool that quietly reports "0 incidents" when it simply
cannot see them is worse than one that admits it does not know.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp
from defusedxml.ElementTree import fromstring as xml_fromstring
from xml.etree.ElementTree import ParseError

from . import __version__

# Indicators, ordered least to most severe.
OK = "operational"
MINOR = "minor"
MAJOR = "major"
CRITICAL = "critical"
UNKNOWN = "unknown"

SEVERITY = {OK: 0, MINOR: 1, MAJOR: 2, CRITICAL: 3, UNKNOWN: 4}

_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=5)
_MAX_BYTES = 8 * 1024 * 1024
_USER_AGENT = f"gwen-cli/{__version__} (+https://github.com/marcodepumper/gwen-cli)"


@dataclass
class Incident:
    name: str
    status: str = ""
    impact: str = ""
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    url: str = ""
    components: list[str] = field(default_factory=list)


@dataclass
class Maintenance:
    name: str
    scheduled_for: datetime | None = None
    scheduled_until: datetime | None = None
    in_progress: bool = False
    url: str = ""
    components: list[str] = field(default_factory=list)


@dataclass
class Component:
    name: str
    status: str


@dataclass
class ProviderStatus:
    """Normalised status for one provider.

    `error` is set when the feed could not be read. In that case `indicator`
    is UNKNOWN and the lists are empty because nothing is known -- not because
    nothing is wrong.
    """

    name: str
    indicator: str = UNKNOWN
    description: str = ""
    updated_at: datetime | None = None
    ongoing: list[Incident] = field(default_factory=list)
    recent: list[Incident] = field(default_factory=list)
    maintenance: list[Maintenance] = field(default_factory=list)
    degraded: list[Component] = field(default_factory=list)
    supports_history: bool = True
    supports_maintenance: bool = True
    supports_components: bool = True
    error: str | None = None

    @property
    def healthy(self) -> bool:
        return self.indicator == OK and not self.ongoing


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _read(session: aiohttp.ClientSession, url: str) -> bytes:
    """GET *url*, bounded in both time and response size."""
    async with session.get(url, timeout=_TIMEOUT) as response:
        response.raise_for_status()
        declared = response.content_length
        if declared is not None and declared > _MAX_BYTES:
            raise ValueError(f"response too large: {declared} bytes")

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.content.iter_chunked(65536):
            total += len(chunk)
            if total > _MAX_BYTES:
                raise ValueError(f"response exceeded {_MAX_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)


async def _read_json(session: aiohttp.ClientSession, url: str):
    return json.loads(await _read(session, url))


def _parse_iso(value) -> datetime | None:
    """Parse an ISO-8601 timestamp, assuming UTC when no offset is given."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_rfc822(value) -> datetime | None:
    """Parse an RFC-822 date as used in RSS `pubDate` fields."""
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text(element, tag: str) -> str:
    found = element.find(tag)
    return (found.text or "").strip() if found is not None else ""


class Provider:
    """Base class. Subclasses implement `fetch`.

    The `supports_*` flags describe what this provider's feed can actually
    tell us, so the CLI can render "--" instead of a misleading zero.
    """

    #: Short lowercase identifier used on the command line.
    key: str = ""
    #: Human-readable name shown in output.
    label: str = ""
    #: Source of the data, shown by `gwen providers`.
    source: str = "vendor feed"

    supports_history: bool = True
    supports_maintenance: bool = True
    supports_components: bool = True

    async def fetch(self, session: aiohttp.ClientSession, days: int) -> ProviderStatus:
        raise NotImplementedError

    def status(self, **fields) -> ProviderStatus:
        """Build a `ProviderStatus` pre-filled with this provider's capabilities."""
        return ProviderStatus(
            name=self.label,
            supports_history=self.supports_history,
            supports_maintenance=self.supports_maintenance,
            supports_components=self.supports_components,
            **fields,
        )


class StatuspageProvider(Provider):
    """Any service running Atlassian Statuspage (the v2 public API).

    `summary.json` carries current status, components, unresolved incidents
    and scheduled maintenance in a single request. History needs a second
    request, so it is only made when the caller asks for it.
    """

    source = "Statuspage v2"

    def __init__(self, key: str, label: str, base_url: str):
        self.key = key
        self.label = label
        self.base_url = base_url.rstrip("/")

    async def fetch(self, session, days: int) -> ProviderStatus:
        summary = await _read_json(session, f"{self.base_url}/api/v2/summary.json")

        status = summary.get("status") or {}
        indicator = {"none": OK}.get(status.get("indicator"), status.get("indicator") or UNKNOWN)

        result = self.status(
            indicator=indicator,
            description=status.get("description", ""),
            updated_at=_parse_iso((summary.get("page") or {}).get("updated_at")),
            ongoing=[_statuspage_incident(item) for item in summary.get("incidents", [])],
            maintenance=_statuspage_maintenance(summary.get("scheduled_maintenances", [])),
            degraded=[
                Component(name=component.get("name", "?"), status=component.get("status", UNKNOWN))
                for component in summary.get("components", [])
                if component.get("status") not in (None, "operational")
            ],
        )

        # Not every Statuspage site publishes components -- Atlassian's own
        # page lists none. Zero components means "cannot see them", not
        # "all healthy", so let the result say so.
        result.supports_components = bool(summary.get("components"))

        if days > 0:
            result.recent = await self._history(session, days)
        return result

    async def _history(self, session, days: int) -> list[Incident]:
        data = await _read_json(session, f"{self.base_url}/api/v2/incidents.json")
        cutoff = _now() - timedelta(days=days)
        recent = []
        for item in data.get("incidents", []):
            incident = _statuspage_incident(item)
            if incident.started_at and incident.started_at >= cutoff:
                recent.append(incident)
        return recent


def _statuspage_incident(item: dict) -> Incident:
    return Incident(
        name=item.get("name", "Unnamed incident"),
        status=item.get("status", ""),
        impact=item.get("impact", ""),
        started_at=_parse_iso(item.get("created_at")),
        resolved_at=_parse_iso(item.get("resolved_at")),
        url=item.get("shortlink", ""),
        components=[c.get("name", "") for c in item.get("components", [])],
    )


def _statuspage_maintenance(items: list[dict]) -> list[Maintenance]:
    """Keep maintenance that is upcoming or currently running."""
    now = _now()
    windows = []
    for item in items:
        starts = _parse_iso(item.get("scheduled_for"))
        ends = _parse_iso(item.get("scheduled_until"))
        if ends is not None and ends < now:
            continue
        windows.append(
            Maintenance(
                name=item.get("name", "Unnamed"),
                scheduled_for=starts,
                scheduled_until=ends,
                in_progress=bool(starts and ends and starts <= now <= ends),
                url=item.get("shortlink", ""),
                components=[c.get("name", "") for c in item.get("components", [])],
            )
        )
    return windows


class GCPProvider(Provider):
    """Google Cloud publishes one JSON document of all incidents.

    There is no separate maintenance feed, so maintenance is reported as
    unsupported rather than guessed at from incident titles.
    """

    key = "gcp"
    label = "GCP"
    source = "Cloud Status"
    supports_maintenance = False
    supports_components = False

    URL = "https://status.cloud.google.com/incidents.json"
    SITE = "https://status.cloud.google.com/"

    #: GCP severity values, mapped onto our indicators.
    _SEVERITY = {"low": MINOR, "medium": MAJOR, "high": CRITICAL}

    async def fetch(self, session, days: int) -> ProviderStatus:
        incidents = await _read_json(session, self.URL)
        cutoff = _now() - timedelta(days=days)

        ongoing: list[Incident] = []
        recent: list[Incident] = []
        worst = OK

        for item in incidents:
            began = _parse_iso(item.get("begin"))
            ended = _parse_iso(item.get("end"))
            incident = Incident(
                name=item.get("external_desc", "Unnamed incident"),
                status="resolved" if ended else "ongoing",
                impact=item.get("severity", ""),
                started_at=began,
                resolved_at=ended,
                url=self.SITE + str(item.get("uri", "")).lstrip("/"),
                components=[p.get("title", "") for p in item.get("affected_products", [])],
            )
            if ended is None:
                ongoing.append(incident)
                severity = self._SEVERITY.get(item.get("severity", ""), MINOR)
                if SEVERITY[severity] > SEVERITY[worst]:
                    worst = severity
            elif began and began >= cutoff:
                recent.append(incident)

        return self.status(
            indicator=worst,
            description=(
                f"{len(ongoing)} active incident(s)" if ongoing else "All Systems Operational"
            ),
            updated_at=_now(),
            ongoing=ongoing,
            recent=recent if days > 0 else [],
        )


class AWSProvider(Provider):
    """AWS Health.

    Current events come from the public health JSON; history comes from the
    RSS feed. The older `health.aws.amazon.com/health/status` endpoint used by
    previous versions of this tool now serves HTML, which silently produced an
    empty -- and therefore always-green -- result.
    """

    key = "aws"
    label = "AWS"
    source = "AWS Health"
    supports_maintenance = False
    supports_components = False

    CURRENT = "https://health.aws.amazon.com/public/currentevents"
    HISTORY = "https://status.aws.amazon.com/rss/all.rss"

    #: AWS Health status codes, as used by the service health dashboard.
    _STATUS = {0: OK, 1: MINOR, 2: MAJOR, 3: MAJOR}

    async def fetch(self, session, days: int) -> ProviderStatus:
        ongoing = await self._current(session)
        worst = OK
        for event, indicator in ongoing:
            if SEVERITY[indicator] > SEVERITY[worst]:
                worst = indicator

        incidents = [event for event, _ in ongoing]
        return self.status(
            indicator=worst,
            description=(
                f"{len(incidents)} active event(s)" if incidents else "All Systems Operational"
            ),
            updated_at=_now(),
            ongoing=incidents,
            recent=await self._history(session, days) if days > 0 else [],
        )

    async def _current(self, session) -> list[tuple[Incident, str]]:
        # Served as UTF-16 with a mislabelled charset header, so decode by hand.
        raw = await _read(session, self.CURRENT)
        events = json.loads(raw.decode("utf-16"))

        results = []
        for event in events:
            region = event.get("region_name") or ""
            service = event.get("service_name") or "AWS"
            name = f"{service}: {event.get('summary', 'Service event')}"
            if region:
                name = f"{name} ({region})"

            started = None
            if str(event.get("date", "")).isdigit():
                started = datetime.fromtimestamp(int(event["date"]), tz=timezone.utc)

            try:
                code = int(event.get("status", 1))
            except (TypeError, ValueError):
                code = 1

            results.append(
                (
                    Incident(
                        name=name,
                        status="ongoing",
                        impact=self._STATUS.get(code, MINOR),
                        started_at=started,
                        url="https://health.aws.amazon.com/health/status",
                        components=[service],
                    ),
                    self._STATUS.get(code, MINOR),
                )
            )
        return results

    async def _history(self, session, days: int) -> list[Incident]:
        feed = xml_fromstring(await _read(session, self.HISTORY))
        cutoff = _now() - timedelta(days=days)

        recent = []
        for item in feed.findall(".//item"):
            published = _parse_rfc822(_text(item, "pubDate"))
            if published is None or published < cutoff:
                continue
            title = _text(item, "title")
            recent.append(
                Incident(
                    name=title or "AWS service event",
                    status="resolved" if "resolved" in title.lower() else "ongoing",
                    started_at=published,
                    resolved_at=published if "resolved" in title.lower() else None,
                    url=_text(item, "link"),
                )
            )
        return recent


class AzureProvider(Provider):
    """Azure's status RSS feed.

    The feed lists only *current* issues -- it carries no incident history and
    no maintenance calendar, so both are reported as unsupported.

    An empty feed normally means "nothing wrong", but it would look identical
    to a feed that had been quietly retired. `lastBuildDate` distinguishes the
    two: a feed that has not been rebuilt in weeks is treated as unusable
    rather than as good news.
    """

    key = "azure"
    label = "Azure"
    source = "Status RSS"
    supports_history = False
    supports_maintenance = False
    supports_components = False

    URL = "https://azure.status.microsoft/en-us/status/feed/"
    STALE_AFTER = timedelta(days=7)

    _ONGOING_HINTS = ("investigating", "identified", "monitoring", "degraded", "outage", "impact")

    async def fetch(self, session, days: int) -> ProviderStatus:
        feed = xml_fromstring(await _read(session, self.URL))
        channel = feed.find("channel")
        if channel is None:
            raise ValueError("Azure status feed is missing its channel element")

        built = _parse_rfc822(_text(channel, "lastBuildDate"))
        if built is not None and _now() - built > self.STALE_AFTER:
            return self.status(
                indicator=UNKNOWN,
                description="Status feed appears stale",
                updated_at=built,
                error=f"feed last rebuilt {built:%Y-%m-%d}; treating as unavailable",
            )

        ongoing = []
        for item in channel.findall("item"):
            title = _text(item, "title")
            if not title:
                continue
            ongoing.append(
                Incident(
                    name=title,
                    status="investigating",
                    impact=MINOR if _is_ongoing(title, self._ONGOING_HINTS) else "",
                    started_at=_parse_rfc822(_text(item, "pubDate")),
                    url=_text(item, "link"),
                )
            )

        return self.status(
            indicator=MINOR if ongoing else OK,
            description=(
                f"{len(ongoing)} active issue(s)" if ongoing else "All Systems Operational"
            ),
            updated_at=built or _now(),
            ongoing=ongoing,
        )


def _is_ongoing(title: str, hints: tuple[str, ...]) -> bool:
    lowered = title.lower()
    return any(hint in lowered for hint in hints)


PROVIDERS: dict[str, Provider] = {
    provider.key: provider
    for provider in (
        StatuspageProvider("cloudflare", "Cloudflare", "https://www.cloudflarestatus.com"),
        AWSProvider(),
        AzureProvider(),
        GCPProvider(),
        StatuspageProvider("github", "GitHub", "https://www.githubstatus.com"),
        StatuspageProvider("datadog", "Datadog", "https://status.datadoghq.com"),
        StatuspageProvider("atlassian", "Atlassian", "https://status.atlassian.com"),
    )
}


def resolve(name: str) -> Provider:
    """Look up a provider by key, accepting the legacy `CloudflareAgent` form."""
    key = name.strip().lower()
    if key.endswith("agent"):
        key = key[: -len("agent")]
    try:
        return PROVIDERS[key]
    except KeyError:
        raise KeyError(
            f"Unknown provider {name!r}. Available: {', '.join(sorted(PROVIDERS))}"
        ) from None


async def _fetch_one(session, provider: Provider, days: int) -> ProviderStatus:
    """Fetch one provider, converting any failure into an explicit UNKNOWN."""
    try:
        return await provider.fetch(session, days)
    except asyncio.TimeoutError:
        error = "timed out"
    except aiohttp.ClientError as exc:
        error = f"network error: {exc}"
    # ParseError is a SyntaxError, not a ValueError, so it needs naming
    # explicitly -- otherwise one malformed feed takes down the whole run.
    except (ValueError, KeyError, TypeError, ParseError) as exc:
        error = f"could not read feed: {exc}"
    return provider.status(
        indicator=UNKNOWN, description="Status unavailable", error=error
    )


async def gather(names: list[str] | None = None, days: int = 14) -> list[ProviderStatus]:
    """Fetch every requested provider concurrently over a single connection pool."""
    selected = [resolve(name) for name in names] if names else list(PROVIDERS.values())

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(
        connector=connector, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT
    ) as session:
        return list(
            await asyncio.gather(*(_fetch_one(session, p, days) for p in selected))
        )
