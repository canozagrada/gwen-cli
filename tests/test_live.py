"""Opt-in checks against the real endpoints.

Skipped by default; run with `pytest -m live`.

The recorded fixtures prove the parsers handle the shape the feeds had when
they were captured. These prove the feeds still have that shape. That is the
gap that let AWS and Azure drift into reporting a permanent all-clear -- the
code kept working perfectly against data that had stopped arriving.

Run these on a schedule, not on every commit: they need network access and
depend on someone else's uptime.
"""

from __future__ import annotations

import json

import aiohttp
import pytest

from conftest import run

from gwen_cli import providers

pytestmark = pytest.mark.live

STATUSPAGE = [p for p in providers.PROVIDERS.values()
              if isinstance(p, providers.StatuspageProvider)]


async def get(url: str) -> bytes:
    async with aiohttp.ClientSession(headers={"User-Agent": providers._USER_AGENT}) as session:
        return await providers._read(session, url)


def test_every_provider_still_reports_something_usable():
    """The single most valuable check: nothing silently degrades to UNKNOWN."""
    results = run(providers.gather(days=14))

    broken = [f"{r.name}: {r.error}" for r in results if r.indicator == providers.UNKNOWN]
    assert not broken, "provider feeds no longer usable:\n  " + "\n  ".join(broken)
    assert len(results) == len(providers.PROVIDERS)


@pytest.mark.parametrize("provider", STATUSPAGE, ids=[p.key for p in STATUSPAGE])
def test_statuspage_summary_shape(provider):
    data = json.loads(run(get(f"{provider.base_url}/api/v2/summary.json")))

    for key in ("status", "page", "components", "incidents", "scheduled_maintenances"):
        assert key in data, f"{provider.key} summary.json no longer has {key!r}"
    assert "indicator" in data["status"]
    assert "description" in data["status"]

    # Some pages publish no components at all (Atlassian's does not), which is
    # legitimate -- but any that are published must still have a status.
    for component in data["components"]:
        assert "name" in component and "status" in component


def test_aws_current_events_still_utf16_json():
    raw = run(get(providers.AWSProvider.CURRENT))

    events = json.loads(raw.decode("utf-16"))
    assert isinstance(events, list)
    for event in events:
        for key in ("date", "service_name", "summary", "status"):
            assert key in event, f"AWS event no longer has {key!r}"


def test_aws_history_feed_still_has_items():
    from defusedxml.ElementTree import fromstring

    feed = fromstring(run(get(providers.AWSProvider.HISTORY)))
    items = feed.findall(".//item")

    assert items, "AWS RSS feed returned no items -- the endpoint may have moved"


def test_azure_feed_is_still_being_rebuilt():
    """An empty Azure feed is only good news if it is still being maintained."""
    from defusedxml.ElementTree import fromstring

    feed = fromstring(run(get(providers.AzureProvider.URL)))
    channel = feed.find("channel")
    assert channel is not None, "Azure feed has no channel element"

    built = providers._parse_rfc822(providers._text(channel, "lastBuildDate"))
    assert built is not None, "Azure feed has no parseable lastBuildDate"

    age = providers._now() - built
    assert age < providers.AzureProvider.STALE_AFTER, (
        f"Azure feed last rebuilt {age.days} days ago; it may have been retired"
    )


def test_gcp_incidents_shape():
    data = json.loads(run(get(providers.GCPProvider.URL)))

    assert isinstance(data, list) and data, "GCP incidents.json is empty or not a list"
    for key in ("id", "begin", "external_desc", "affected_products"):
        assert key in data[0], f"GCP incident no longer has {key!r}"
