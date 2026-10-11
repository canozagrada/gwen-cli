"""`gwen investigate` and `gwen regions`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gwen_cli import cli, history, investigate, policy, providers, watch
from gwen_cli.targets import Target

T0 = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
SCUS = Target("azure", "southcentralus")
NCUS = Target("azure", "northcentralus")


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(providers, "PROVIDERS", dict(providers.PROVIDERS))


def ev(key, provider, title, priority=3, kind="incident", targets=(), regions=()):
    return watch.Event(
        provider,
        kind,
        f"new incident: {title}",
        title=title,
        key=key,
        priority=priority,
        targets=list(targets),
        regions=list(regions),
        text=title.lower(),
    )


def record(path, minutes, event, route=history.LOG):
    history.record(path, [(event, route)], T0 + timedelta(minutes=minutes))


@pytest.fixture
def log(tmp_path):
    path = tmp_path / ".gwen-history.sqlite"
    record(
        path,
        -90,
        ev("gcp", "GCP", "Networking issue in us-south1", regions=["us-south1"]),
    )
    record(path, -30, ev("azure", "Azure", "Latency in North Central US"))
    record(
        path,
        -10,
        ev(
            "cloudflare",
            "Cloudflare",
            "Dallas, TX, United States - (DFW)",
            kind="degraded",
        ),
    )
    record(
        path,
        0,
        ev(
            "azure",
            "Azure",
            "Outage in South Central US",
            1,
            targets=["azure/southcentralus"],
        ),
        history.NOTIFY,
    )
    record(path, 20, ev("azure", "Azure", "Storage in West Europe"))
    record(path, 45, ev("aws", "AWS", "Errors (Tokyo)", regions=["ap-northeast-1"]))
    record(path, 300, ev("azure", "Azure", "Much later in South Central US"))
    return path


def azure_policy():
    return policy.Policy(
        policy.parse_rules(
            [
                {"target": "azure/scus", "priority": 1, "failover": ["azure/ncus"]},
                {"target": "azure/ncus", "priority": 2},
            ]
        )
    )


def test_window_and_time_parsing():
    assert investigate.parse_window("90m") == timedelta(minutes=90)
    assert investigate.parse_window("2h") == timedelta(hours=2)
    assert investigate.parse_window("1d") == timedelta(days=1)
    with pytest.raises(ValueError):
        investigate.parse_window("two hours")
    assert investigate.parse_moment("2026-10-12T15:00:00Z") == T0
    assert investigate.parse_moment("2026-10-12 10:00").tzinfo is not None


def test_relations_around_the_last_problem(log):
    at, findings = investigate.investigate(
        log, SCUS, azure_policy(), at=T0, window=timedelta(hours=2)
    )
    assert at == T0
    related = [(f.row["title"], f.relation) for f in findings]
    assert related == [
        ("Networking issue in us-south1", "area"),
        ("Latency in North Central US", "failover"),
        ("Dallas, TX, United States - (DFW)", "area"),
        ("Outage in South Central US", "target"),
        ("Storage in West Europe", "provider"),
        ("Errors (Tokyo)", "other"),
    ]
    assert findings[0].offset == timedelta(minutes=-90)


def test_anchor_defaults_to_the_most_recent_problem(log):
    at, findings = investigate.investigate(
        log, SCUS, azure_policy(), window=timedelta(minutes=30)
    )
    assert at == T0 + timedelta(minutes=300)
    assert [f.row["title"] for f in findings] == ["Much later in South Central US"]


def test_no_recorded_problem(tmp_path, log):
    at, findings = investigate.investigate(
        log, Target("aws", "us-east-1"), policy.Policy()
    )
    assert at is None and findings == []


def invoke(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["gwen", *argv])
    return cli.main()


def test_investigate_command(tmp_path, monkeypatch, log, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gwen.toml").write_text(
        '[[watch.rule]]\ntarget = "azure/scus"\npriority = 1\nfailover = ["azure/ncus"]\n',
        encoding="utf-8",
    )
    code = invoke(
        monkeypatch, "investigate", "azure/scus", "--at", "2026-10-12T15:00:00Z"
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "azure/southcentralus around" in out
    assert "failover" in out and "-30m" in out
    assert "related changes were priority 3 and not sent" in out


def test_investigate_without_history(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert invoke(monkeypatch, "investigate", "azure/scus") == 0
    assert "No history" in capsys.readouterr().out


def test_investigate_bad_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert invoke(monkeypatch, "investigate", "azure/atlantis") == 2


def test_regions_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert invoke(monkeypatch, "regions", "azure") == 0
    out = capsys.readouterr().out
    assert "azure/southcentralus" in out and "scus" in out and "northcentralus" in out
