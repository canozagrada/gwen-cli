"""Regions: `azure/scus` on the command line, and `gwen regions`."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conftest import load, load_json, run

from gwen_cli import cli, providers, targets
from gwen_cli.providers import (
    MAJOR,
    MINOR,
    OK,
    Component,
    Incident,
    Maintenance,
    ProviderStatus,
)
from gwen_cli.targets import Target

SCUS = Target("azure", "southcentralus")


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(providers, "PROVIDERS", dict(providers.PROVIDERS))


def incident(name, *components, regions=()):
    return Incident(
        name=name,
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        url="https://status.example/i",
        components=list(components),
        regions=list(regions),
    )


# --- parsing and matching ---------------------------------------------------


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("azure/scus", Target("azure", "southcentralus")),
        ("Azure/South Central US", Target("azure", "southcentralus")),
        ("azure/southcentralus", Target("azure", "southcentralus")),
        ("aws/us-east-1", Target("aws", "us-east-1")),
        ("gcp/us-central1", Target("gcp", "us-central1")),
        ("cloudflare/DFW", Target("cloudflare", "dfw")),
        ("github", Target("github")),
    ],
)
def test_parse_targets(spec, expected):
    assert targets.parse(spec) == expected


@pytest.mark.parametrize(
    "spec,complaint",
    [("azure/scuss", "gwen regions azure"), ("nope/x", "Unknown provider")],
)
def test_bad_targets_say_why(spec, complaint):
    with pytest.raises(targets.TargetError, match=complaint):
        targets.parse(spec)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Degraded storage in South Central US", {"southcentralus"}),
        ("Degraded storage in Central US", {"centralus"}),
        ("Networking issue in East US 2", {"eastus2"}),
        ("Networking issue in East US and East US 2", {"eastus", "eastus2"}),
        ("Storage errors - West Europe / North Europe", {"westeurope", "northeurope"}),
        ("Global DNS resolution failures", set()),
    ],
)
def test_azure_region_names_do_not_bleed_into_each_other(text, expected):
    assert targets.mentioned("azure", text) == expected


def test_explicit_region_codes_count():
    assert targets.mentioned("aws", "Increased error rates", ["us-east-1"]) == {
        "us-east-1"
    }


def test_unnamed_region_affects_every_region_of_a_catalog_provider():
    assert targets.matches(SCUS, "global dns failures")
    assert not targets.matches(SCUS, "issue in west europe")


def test_catalogless_providers_match_whole_words():
    dfw = Target("cloudflare", "dfw")
    assert targets.matches(dfw, "Dallas, TX, United States - (DFW)")
    assert not targets.matches(dfw, "dfwx maintenance")
    assert not targets.matches(dfw, "elevated errors in china network colos")


def test_aws_and_gcp_feeds_supply_region_codes(stub_feeds):
    stub_feeds(
        {
            "currentevents": json.dumps(load_json("aws_currentevents.json")).encode(
                "utf-16"
            )
        }
    )
    aws = run(providers._fetch_one(None, providers.AWSProvider(), 0))
    assert aws.ongoing[0].regions == ["me-central-1"]

    gcp_data = json.loads(load("gcp_incidents.json"))
    gcp_data[0]["end"] = None
    gcp_data[0]["currently_affected_locations"] = [
        {"title": "Iowa", "id": "us-central1"}
    ]
    stub_feeds({"incidents.json": json.dumps(gcp_data).encode()})
    gcp = run(providers._fetch_one(None, providers.GCPProvider(), 0))
    assert gcp.ongoing[0].regions == ["us-central1"]


# --- narrowing a provider to a region ----------------------------------------


def azure(*ongoing, indicator=MAJOR):
    return ProviderStatus(name="Azure", indicator=indicator, ongoing=list(ongoing))


def test_narrow_keeps_this_region_and_unplaced_incidents():
    result = azure(
        incident("Outage in South Central US"),
        incident("Storage in West Europe"),
        incident("Global DNS failures"),
    )
    narrowed = cli.narrow(result, SCUS)

    assert [i.name for i in narrowed.ongoing] == [
        "Outage in South Central US",
        "Global DNS failures",
    ]
    assert narrowed.indicator == MAJOR
    assert narrowed.name == "Azure southcentralus"
    assert not cli.unplaced(SCUS, narrowed.ongoing[0])
    assert cli.unplaced(SCUS, narrowed.ongoing[1])


def test_narrow_elsewhere_only_is_ok_for_this_region():
    narrowed = cli.narrow(azure(incident("Storage in West Europe")), SCUS)
    assert narrowed.ongoing == [] and narrowed.indicator == OK


def test_narrow_never_reports_ok_for_a_matching_incident():
    narrowed = cli.narrow(
        azure(incident("Latency in South Central US"), indicator=OK), SCUS
    )
    assert narrowed.indicator == MINOR


def test_narrow_filters_components_and_maintenance():
    result = ProviderStatus(
        name="Cloudflare",
        indicator=MINOR,
        degraded=[
            Component("Dallas, TX, United States - (DFW)", "partial_outage"),
            Component("Lima, Peru - (LIM)", "partial_outage"),
        ],
        maintenance=[
            Maintenance("DFW (Dallas) on 2026-10-14"),
            Maintenance("LIM (Lima) on 2026-10-14"),
        ],
    )
    narrowed = cli.narrow(result, Target("cloudflare", "dfw"))
    assert [c.name for c in narrowed.degraded] == ["Dallas, TX, United States - (DFW)"]
    assert [m.name for m in narrowed.maintenance] == ["DFW (Dallas) on 2026-10-14"]


def test_narrow_leaves_unreadable_feeds_alone():
    broken = ProviderStatus(name="Azure", error="timed out")
    assert cli.narrow(broken, SCUS) is broken


# --- command line -----------------------------------------------------------


def invoke(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["gwen", *argv])
    return cli.main()


@pytest.fixture
def azure_feed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    requested = []

    def fetch(names, days):
        requested.append(names)
        return [
            azure(
                incident("Outage in South Central US"),
                incident("Storage in West Europe"),
                incident("Global DNS failures"),
            )
        ]

    monkeypatch.setattr(cli, "fetch", fetch)
    return requested


def test_status_for_a_region(monkeypatch, azure_feed, capsys):
    assert invoke(monkeypatch, "status", "azure/scus") == 0
    out = capsys.readouterr().out

    assert azure_feed == [["azure"]]
    assert "Azure southcentralus" in out
    assert "Outage in South Central US" in out
    assert "West Europe" not in out
    assert "Global DNS failures (names no region; may affect it)" in out
    assert "Azure overall: major" in out


def test_incidents_for_a_region(monkeypatch, azure_feed, capsys):
    assert invoke(monkeypatch, "incidents", "azure/scus") == 0
    out = capsys.readouterr().out
    assert "Outage in South Central US" in out and "West Europe" not in out


def test_unknown_region_is_a_usage_error(monkeypatch, azure_feed, capsys):
    assert invoke(monkeypatch, "status", "azure/atlantis") == 2
    assert "gwen regions azure" in capsys.readouterr().out
    assert azure_feed == [], "nothing is fetched for a bad target"


def test_regions_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert invoke(monkeypatch, "regions", "azure") == 0
    out = capsys.readouterr().out
    assert "azure/southcentralus" in out and "scus" in out and "northcentralus" in out
