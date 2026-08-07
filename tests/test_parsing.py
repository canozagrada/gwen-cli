"""Each provider must pull real data out of its vendor's real payload shape.

These run against recorded responses, so they fail if a parser stops
extracting what it should -- which is exactly how the AWS and Azure feeds
went unnoticed when they moved.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from conftest import load, load_json, run

from gwen_cli import providers
from gwen_cli.providers import MAJOR, MINOR, OK, UNKNOWN


def cloudflare() -> providers.StatuspageProvider:
    return providers.StatuspageProvider("cloudflare", "Cloudflare", "https://status.example")


def test_statuspage_reads_status_components_and_maintenance(stub_feeds):
    stub_feeds({"summary.json": load("statuspage_summary.json")})

    result = run(cloudflare().fetch(None, days=0))

    assert result.indicator in (OK, MINOR, providers.MAJOR, providers.CRITICAL)
    assert result.description, "status description should be populated"
    assert result.updated_at is not None

    # The recorded page had degraded components and maintenance windows.
    assert result.degraded, "degraded components should be extracted"
    assert all(c.status != "operational" for c in result.degraded)
    assert result.maintenance, "maintenance windows should be extracted"
    assert all(w.name for w in result.maintenance)
    assert any(w.scheduled_for is not None for w in result.maintenance)


def test_statuspage_skips_history_request_when_not_asked(stub_feeds):
    feeds = stub_feeds({"summary.json": load("statuspage_summary.json")})

    run(cloudflare().fetch(None, days=0))

    assert not any("incidents.json" in url for url in feeds.requested)


def test_statuspage_history_honours_the_day_window(stub_feeds):
    now = datetime.now(timezone.utc)
    payload = {
        "incidents": [
            {"name": "three days ago", "created_at": (now - timedelta(days=3)).isoformat()},
            {"name": "twenty days ago", "created_at": (now - timedelta(days=20)).isoformat()},
        ]
    }
    stub_feeds({
        "summary.json": load("statuspage_summary.json"),
        "incidents.json": json.dumps(payload).encode(),
    })

    week = run(cloudflare().fetch(None, days=7))
    month = run(cloudflare().fetch(None, days=30))

    assert [i.name for i in week.recent] == ["three days ago"]
    assert len(month.recent) == 2


def test_statuspage_drops_maintenance_that_already_ended(stub_feeds):
    now = datetime.now(timezone.utc)
    payload = {
        "status": {"indicator": "none", "description": "All Systems Operational"},
        "page": {"updated_at": now.isoformat()},
        "components": [],
        "incidents": [],
        "scheduled_maintenances": [
            {
                "name": "finished",
                "scheduled_for": (now - timedelta(days=3)).isoformat(),
                "scheduled_until": (now - timedelta(days=2)).isoformat(),
            },
            {
                "name": "running now",
                "scheduled_for": (now - timedelta(hours=1)).isoformat(),
                "scheduled_until": (now + timedelta(hours=1)).isoformat(),
            },
            {
                "name": "upcoming",
                "scheduled_for": (now + timedelta(days=2)).isoformat(),
                "scheduled_until": (now + timedelta(days=3)).isoformat(),
            },
        ],
    }
    stub_feeds({"summary.json": json.dumps(payload).encode()})

    result = run(cloudflare().fetch(None, days=0))

    assert [w.name for w in result.maintenance] == ["running now", "upcoming"]
    assert [w.in_progress for w in result.maintenance] == [True, False]


def test_aws_decodes_utf16_current_events(stub_feeds):
    # AWS serves this as UTF-16 while labelling it something else entirely.
    events = json.dumps(load_json("aws_currentevents.json")).encode("utf-16")
    stub_feeds({"currentevents": events})

    result = run(providers.AWSProvider().fetch(None, days=0))

    assert result.ongoing, "recorded feed contains active events"
    assert result.indicator in (MINOR, MAJOR), "active events must not read as operational"
    assert all(incident.name for incident in result.ongoing)
    assert all(incident.started_at is not None for incident in result.ongoing)


def test_aws_reads_history_from_rss(stub_feeds):
    events = json.dumps(load_json("aws_currentevents.json")).encode("utf-16")
    stub_feeds({"currentevents": events, "all.rss": load("aws_history.rss")})

    # The recorded RSS items are older than any sane window, so reach back far.
    result = run(providers.AWSProvider().fetch(None, days=40000))

    assert result.recent, "history items should be extracted from the RSS feed"
    assert all(incident.started_at is not None for incident in result.recent)


def test_gcp_separates_ongoing_from_resolved(stub_feeds):
    stub_feeds({"incidents.json": load("gcp_incidents.json")})

    result = run(providers.GCPProvider().fetch(None, days=40000))

    assert result.recent, "recorded feed contains resolved incidents"
    assert all(i.resolved_at is not None for i in result.recent)
    assert all(i.resolved_at is None for i in result.ongoing)
    assert all(i.url.startswith("https://status.cloud.google.com/") for i in result.recent)


def test_azure_empty_but_freshly_built_feed_is_operational(stub_feeds):
    feed = _azure_with_build_date(load("azure_feed.xml"), datetime.now(timezone.utc))
    stub_feeds({"status/feed": feed})

    result = run(providers.AzureProvider().fetch(None, days=0))

    assert result.indicator == OK
    assert result.ongoing == []
    assert result.error is None


def test_azure_stale_feed_is_unknown_not_operational(stub_feeds):
    """A feed that stopped being rebuilt must not read as good news."""
    stale = datetime.now(timezone.utc) - timedelta(days=60)
    stub_feeds({"status/feed": _azure_with_build_date(load("azure_feed.xml"), stale)})

    result = run(providers.AzureProvider().fetch(None, days=0))

    assert result.indicator == UNKNOWN
    assert result.error is not None


def test_azure_items_become_incidents(stub_feeds):
    feed = _azure_with_build_date(
        load("azure_feed_with_items.xml"), datetime.now(timezone.utc)
    )
    stub_feeds({"status/feed": feed})

    result = run(providers.AzureProvider().fetch(None, days=0))

    assert len(result.ongoing) == 2
    assert result.indicator == MINOR
    assert all(incident.started_at is not None for incident in result.ongoing)


def _azure_with_build_date(feed: bytes, moment: datetime) -> bytes:
    """Rewrite lastBuildDate so staleness tests do not rot as the fixture ages."""
    stamp = moment.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S Z")
    return re.sub(
        rb"<lastBuildDate>.*?</lastBuildDate>",
        f"<lastBuildDate>{stamp}</lastBuildDate>".encode(),
        feed,
    )
