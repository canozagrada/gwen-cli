"""A broken feed must never look like a healthy one.

This is the failure the previous version shipped with: two vendors moved their
endpoints, the parsers quietly produced nothing, and "nothing" rendered as
"All Systems Operational" for months.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from conftest import run

from gwen_cli import providers, regions
from gwen_cli.providers import OK, UNKNOWN

# One entry per provider: an instance plus a URL fragment its fetch will request.
CASES = [
    (providers.StatuspageProvider("github", "GitHub", "https://status.example"), "summary.json"),
    (providers.AWSProvider(), "currentevents"),
    (providers.AzureProvider(), "status/feed"),
    (providers.GCPProvider(), "incidents.json"),
]
IDS = [provider.label for provider, _ in CASES]


def fetch_one(provider, payload_or_error, fragment, stub_feeds, days=0):
    """Fetch through the real error handling. No session is needed -- the
    stubbed reader ignores it and nothing touches the network."""
    stub_feeds({fragment: payload_or_error})
    return run(providers._fetch_one(None, provider, days))


@pytest.mark.parametrize("provider,fragment", CASES, ids=IDS)
def test_html_error_page_never_reports_operational(provider, fragment, stub_feeds):
    """The exact AWS regression: the endpoint starts serving HTML."""
    html = b"<!DOCTYPE html><html><body>Moved. See our new status page.</body></html>"

    result = fetch_one(provider, html, fragment, stub_feeds)

    assert result.indicator == UNKNOWN, f"{provider.label} reported {result.indicator}"
    assert result.error, "the reason should be reported to the user"
    assert not result.ongoing and not result.recent


@pytest.mark.parametrize("provider,fragment", CASES, ids=IDS)
def test_empty_payload_never_reports_operational(provider, fragment, stub_feeds):
    result = fetch_one(provider, b"", fragment, stub_feeds)

    assert result.indicator == UNKNOWN
    assert result.error


@pytest.mark.parametrize("provider,fragment", CASES, ids=IDS)
def test_network_failure_reports_unknown(provider, fragment, stub_feeds):
    failure = aiohttp.ClientError("connection refused")

    result = fetch_one(provider, failure, fragment, stub_feeds)

    assert result.indicator == UNKNOWN
    assert "network error" in result.error


@pytest.mark.parametrize("provider,fragment", CASES, ids=IDS)
def test_timeout_reports_unknown(provider, fragment, stub_feeds):
    result = fetch_one(provider, asyncio.TimeoutError(), fragment, stub_feeds)

    assert result.indicator == UNKNOWN
    assert result.error == "timed out"


def test_malformed_xml_degrades_instead_of_crashing(stub_feeds):
    """ParseError is a SyntaxError, so it must be caught by name."""
    result = fetch_one(
        providers.AzureProvider(), b"<rss><channel><unclosed>", "status/feed", stub_feeds
    )

    assert result.indicator == UNKNOWN
    assert "could not read feed" in result.error


def test_one_broken_provider_does_not_affect_the_others(stub_feeds):
    stub_feeds({
        "githubstatus": aiohttp.ClientError("refused"),
        "summary.json": b'{"status":{"indicator":"none","description":"All Systems Operational"},'
                        b'"page":{},"components":[],"incidents":[],"scheduled_maintenances":[]}',
    })

    results = run(providers.gather(["github", "datadog", "atlassian"], days=0))
    by_name = {r.name: r for r in results}

    assert by_name["GitHub"].indicator == UNKNOWN
    assert by_name["Datadog"].indicator == OK
    assert by_name["Atlassian"].indicator == OK


def test_providers_that_cannot_see_maintenance_say_so():
    """An empty list plus a False flag; never an empty list presented as fact."""
    for provider in providers.PROVIDERS.values():
        result = provider.status()
        assert result.supports_maintenance == provider.supports_maintenance
        if not provider.supports_maintenance:
            assert result.maintenance == []


def test_a_page_with_no_components_does_not_claim_they_are_healthy(stub_feeds):
    """Atlassian publishes zero components; that is 'cannot see', not 'all OK'."""
    stub_feeds({"summary.json": b'{"status":{"indicator":"none","description":"ok"},'
                                b'"page":{},"components":[],"incidents":[],'
                                b'"scheduled_maintenances":[]}'})
    provider = providers.StatuspageProvider("atlassian", "Atlassian", "https://status.example")

    result = run(provider.fetch(None, days=0))

    assert result.supports_components is False
    assert result.degraded == []


def test_a_page_with_components_reports_them(stub_feeds):
    stub_feeds({"summary.json": b'{"status":{"indicator":"none","description":"ok"},'
                                b'"page":{},"components":['
                                b'{"name":"API","status":"operational"},'
                                b'{"name":"Web","status":"degraded_performance"}],'
                                b'"incidents":[],"scheduled_maintenances":[]}'})
    provider = providers.StatuspageProvider("github", "GitHub", "https://status.example")

    result = run(provider.fetch(None, days=0))

    assert result.supports_components is True
    assert [c.name for c in result.degraded] == ["Web"]


def test_azure_declares_it_has_no_history():
    assert providers.AzureProvider().supports_history is False


def test_registry_keys_are_consistent():
    for key, provider in providers.PROVIDERS.items():
        assert provider.key == key
        assert provider.label
        assert provider.source


def test_resolve_accepts_case_and_the_legacy_agent_suffix():
    assert providers.resolve("cloudflare").key == "cloudflare"
    assert providers.resolve("CloudflareAgent").key == "cloudflare"
    assert providers.resolve("  AWS  ").key == "aws"


def test_resolve_rejects_unknown_names():
    with pytest.raises(KeyError) as caught:
        providers.resolve("nosuchthing")
    assert "cloudflare" in str(caught.value), "the error should list valid names"


def test_region_classification():
    assert regions.classify("Dallas, Texas - (DFW)") == "North America"
    assert regions.classify("Frankfurt, Germany - (FRA)") == "Europe"
    assert regions.classify("Singapore - (SIN)") == "Asia"
    assert regions.classify("Baghdad, Iraq - (BGW)") == "Middle East"
    assert regions.classify("somewhere unlabelled") == regions.OTHER


def test_location_codes():
    assert regions.location_code("Dallas, Texas - (DFW)") == "DFW"
    assert regions.location_code("no code here") == "NO"
    assert regions.location_code("") == "???"
