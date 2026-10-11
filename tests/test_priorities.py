"""Priorities per target, work hours, failover, and the history they feed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import load, load_json, run

from gwen_cli import cli, config, history, policy, providers, targets, watch
from gwen_cli.providers import (
    MAJOR,
    MINOR,
    OK,
    UNKNOWN,
    Component,
    Incident,
    ProviderStatus,
)
from gwen_cli.targets import Target

CHICAGO = "America/Chicago"
# Monday 2026-10-12, 15:00 UTC = 10:00 in Chicago: inside Mon-Fri 08:00-18:00.
WORKDAY = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
# Sunday 2026-10-11, 15:00 UTC: outside.
WEEKEND = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(providers, "PROVIDERS", dict(providers.PROVIDERS))


def write(tmp_path, text: str):
    path = tmp_path / "gwen.toml"
    path.write_text(text, encoding="utf-8")
    return path


def make_policy(rules: str, default: int | None = None) -> policy.Policy:
    """Build a policy from TOML rule tables, as the config would."""
    from gwen_cli.config import tomllib

    data = tomllib.loads(rules)
    return policy.Policy(
        policy.parse_rules(data.get("rule", [])),
        default if default is not None else policy.LOG,
        policy.parse_schedule("Mon-Fri 08:00-18:00", CHICAGO),
        explicit_default=default is not None,
    )


AZURE_RULES = """
[[rule]]
target = "azure/scus"
priority = 1
failover = ["azure/ncus"]

[[rule]]
target = "azure/ncus"
priority = 2
"""


def incident(name, *components, regions=()):
    return Incident(
        name=name,
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        url="https://status.example/i",
        components=list(components),
        regions=list(regions),
    )


def status(name="Azure", indicator=OK, ongoing=(), degraded=(), error=None):
    return ProviderStatus(
        name=name,
        indicator=indicator,
        ongoing=list(ongoing),
        degraded=list(degraded),
        error=error,
    )


def step(results, previous=None, rules=AZURE_RULES, default=None):
    return watch.evaluate(results, previous or {}, {}, 2, make_policy(rules, default))


def by_kind(events):
    return {(e.kind, e.title): e for e in events}


# --- targets ----------------------------------------------------------------


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
    assert targets.matches(Target("azure", "southcentralus"), "global dns failures")
    assert not targets.matches(
        Target("azure", "southcentralus"), "issue in west europe"
    )


def test_catalogless_providers_match_whole_words():
    dfw = Target("cloudflare", "dfw")
    assert targets.matches(dfw, "Dallas, TX, United States - (DFW)")
    assert not targets.matches(dfw, "dfwx maintenance")
    assert not targets.matches(dfw, "elevated errors in china network colos")


def test_aws_and_gcp_feeds_supply_region_codes(stub_feeds):
    stub_feeds({"currentevents": json.dumps(load_json("aws_currentevents.json")).encode("utf-16")})
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


# --- schedule ---------------------------------------------------------------


def test_work_hours_in_a_timezone():
    hours = policy.parse_schedule("Mon-Fri 08:00-18:00", CHICAGO)
    assert hours.contains(WORKDAY)
    assert not hours.contains(WEEKEND)
    assert not hours.contains(WORKDAY + timedelta(hours=9))  # 19:00 Chicago


def test_day_lists_and_wraparound():
    assert policy.parse_schedule("Mon,Wed,Fri 09:00-17:00").days == {0, 2, 4}
    assert policy.parse_schedule("Sat-Mon 09:00-17:00").days == {5, 6, 0}


@pytest.mark.parametrize(
    "text",
    ["weekdays", "Mon-Fri 18:00-08:00", "Mon-Fri 25:00-26:00", "Funday 09:00-17:00"],
)
def test_bad_schedules_are_rejected(text):
    with pytest.raises(policy.PolicyError):
        policy.parse_schedule(text)


def test_unknown_timezone_is_rejected():
    with pytest.raises(policy.PolicyError, match="timezone"):
        policy.parse_schedule("Mon-Fri 08:00-18:00", "Mars/Olympus")


# --- classification ---------------------------------------------------------


def test_region_rules_set_the_priority():
    events, _ = step(
        [
            (
                "azure",
                status(
                    indicator=MINOR, ongoing=[incident("Storage in South Central US")]
                ),
            )
        ]
    )
    new = by_kind(events)[("incident", "Storage in South Central US")]
    assert new.priority == 1
    assert new.targets == ["azure/southcentralus"]


def test_unmatched_region_falls_to_the_default():
    events, _ = step(
        [
            (
                "azure",
                status(indicator=MINOR, ongoing=[incident("Storage in West Europe")]),
            )
        ]
    )
    assert {e.priority for e in events} == {3}


def test_incident_naming_no_region_is_treated_as_everywhere():
    events, _ = step(
        [("azure", status(indicator=MAJOR, ongoing=[incident("Global DNS failures")]))]
    )
    new = by_kind(events)[("incident", "Global DNS failures")]
    assert new.priority == 1
    assert set(new.targets) == {"azure/southcentralus", "azure/northcentralus"}


def test_level_change_takes_the_priority_of_its_cause():
    events, _ = step(
        [
            (
                "azure",
                status(
                    indicator=MINOR, ongoing=[incident("Issue in North Central US")]
                ),
            )
        ]
    )
    priorities = {e.kind: e.priority for e in events}
    assert priorities == {"incident": 2, "worse": 2}


def test_unreadable_feed_is_as_urgent_as_its_most_urgent_target():
    failed = [("azure", status(indicator=UNKNOWN, error="timed out"))]
    _, state = step(failed)
    events, _ = step(failed, state)
    assert [(e.kind, e.priority) for e in events] == [("unreadable", 1)]


def test_without_rules_everything_is_priority_one():
    events, _ = watch.evaluate(
        [
            (
                "azure",
                status(indicator=MINOR, ongoing=[incident("Storage in West Europe")]),
            )
        ],
        {},
        {},
        2,
        policy.Policy(),
    )
    assert {e.priority for e in events} == {1}


def test_provider_rule_without_region():
    rules = '[[rule]]\ntarget = "github"\npriority = 2\n'
    events, _ = step(
        [("github", status("GitHub", MINOR, ongoing=[incident("Actions delays")]))],
        rules=rules,
    )
    assert {e.priority for e in events} == {2}


def test_components_are_tracked_for_region_rules():
    rules = '[[rule]]\ntarget = "cloudflare/dfw"\npriority = 1\n'
    degraded = [
        Component("Dallas, TX, United States - (DFW)", "partial_outage"),
        Component("Lima, Peru - (LIM)", "partial_outage"),
    ]
    events, state = step(
        [("cloudflare", status("Cloudflare", MINOR, degraded=degraded))], rules=rules
    )

    assert list(state["cloudflare"]["degraded"]) == [
        "Dallas, TX, United States - (DFW)"
    ]
    dfw = by_kind(events)[("degraded", "Dallas, TX, United States - (DFW)")]
    assert dfw.priority == 1 and dfw.targets == ["cloudflare/dfw"]


def test_components_split_by_priority():
    rules = '[[rule]]\ntarget = "cloudflare/dfw"\npriority = 1\n[[rule]]\ntarget = "cloudflare/lim"\npriority = 3\n'
    degraded = [
        Component("Dallas, TX, United States - (DFW)", "partial_outage"),
        Component("Lima, Peru - (LIM)", "partial_outage"),
    ]
    events, _ = step(
        [("cloudflare", status("Cloudflare", MINOR, degraded=degraded))], rules=rules
    )
    degraded_events = sorted(
        (e.priority, e.title) for e in events if e.kind == "degraded"
    )
    assert degraded_events == [
        (1, "Dallas, TX, United States - (DFW)"),
        (3, "Lima, Peru - (LIM)"),
    ]


# --- failover ---------------------------------------------------------------


def test_failover_promotes_and_restores():
    down = [
        incident("Outage in South Central US"),
        incident("Elevated latency in North Central US"),
    ]
    events, state = step([("azure", status(indicator=MAJOR, ongoing=down))])

    found = by_kind(events)
    assert found[("incident", "Elevated latency in North Central US")].priority == 1, (
        "ncus is normally priority 2, but scus is down"
    )
    promoted = [e for e in events if e.kind == "failover"]
    assert len(promoted) == 1 and promoted[0].priority == 1
    assert "azure/northcentralus is now priority 1" in promoted[0].summary
    assert state[watch.FAILOVER] == ["azure/northcentralus"]

    # Same picture next run: no repeat.
    again, state = step([("azure", status(indicator=MAJOR, ongoing=down))], state)
    assert again == []

    # scus recovers: ncus goes back to priority 2.
    events, state = step(
        [
            (
                "azure",
                status(
                    indicator=MINOR,
                    ongoing=[incident("Elevated latency in North Central US")],
                ),
            )
        ],
        state,
    )
    assert [e.kind for e in events if e.kind.startswith("failover")] == ["failover-end"]
    assert watch.FAILOVER not in state


def test_failover_requires_priority_one():
    with pytest.raises(policy.PolicyError, match="priority 1"):
        policy.parse_rules(
            [{"target": "azure/ncus", "priority": 2, "failover": ["azure/scus"]}]
        )


# --- routing, holding, history ---------------------------------------------


def test_route():
    events = [watch.Event("A", "incident", "", priority=p) for p in (1, 2, 3)]
    assert [way for _, way in watch.route(events, True)] == ["notify", "notify", "log"]
    assert [way for _, way in watch.route(events, False)] == ["notify", "hold", "log"]


class Recorder:
    label = "recorder"

    def __init__(self):
        self.calls: list[tuple[list, list]] = []

    async def send(self, session, events, held=()):
        self.calls.append((list(events), list(held)))


def run_watch(tmp_path, monkeypatch, results, now, recorder, rules=AZURE_RULES):
    cfg = config.load(
        write(
            tmp_path,
            f'[watch]\ntimezone = "{CHICAGO}"\n'
            + rules.replace("[[rule]]", "[[watch.rule]]"),
        )
    )
    keys = [key for key, _ in results]

    async def gather(names, days):
        return [result for _, result in results]

    monkeypatch.setattr(watch.providers, "gather", gather)
    return run(
        watch.run_once(
            cfg, keys, tmp_path / "state.json", [recorder] if recorder else [], now
        )
    )


def test_priority_two_is_held_overnight_and_sent_in_work_hours(tmp_path, monkeypatch):
    recorder = Recorder()
    ncus = [
        (
            "azure",
            status(indicator=MINOR, ongoing=[incident("Issue in North Central US")]),
        )
    ]
    log = tmp_path / ".gwen-history.sqlite"

    first = run_watch(tmp_path, monkeypatch, ncus, WEEKEND, recorder)
    assert [way for _, way in first.routed] == ["hold", "hold"]
    assert recorder.calls == [], "nothing urgent: nothing sent at the weekend"
    assert len(history.held(log)) == 2

    second = run_watch(tmp_path, monkeypatch, ncus, WORKDAY, recorder)
    assert second.routed == []
    ((sent, held),) = recorder.calls
    assert sent == [] and {e.kind for e in held} == {"incident", "worse"}
    assert all(e.seen for e in held)
    assert history.held(log) == []

    run_watch(tmp_path, monkeypatch, ncus, WORKDAY, recorder)
    assert len(recorder.calls) == 1, "released changes are sent once"


def test_dry_run_leaves_held_changes_held(tmp_path, monkeypatch):
    ncus = [
        (
            "azure",
            status(indicator=MINOR, ongoing=[incident("Issue in North Central US")]),
        )
    ]
    log = tmp_path / ".gwen-history.sqlite"

    run_watch(tmp_path, monkeypatch, ncus, WEEKEND, None)
    dry = run_watch(tmp_path, monkeypatch, ncus, WORKDAY, None)
    assert len(dry.released) == 2
    assert len(history.held(log)) == 2


def test_priority_three_is_recorded_not_sent(tmp_path, monkeypatch):
    recorder = Recorder()
    weu = [
        ("azure", status(indicator=MINOR, ongoing=[incident("Storage in West Europe")]))
    ]

    result = run_watch(tmp_path, monkeypatch, weu, WORKDAY, recorder)

    assert recorder.calls == []
    assert {way for _, way in result.routed} == {"log"}
    rows = history.between(
        tmp_path / ".gwen-history.sqlite",
        WORKDAY - timedelta(1),
        WORKDAY + timedelta(1),
    )
    assert [(r["kind"], r["route"], r["key"]) for r in rows] == [
        ("incident", "log", "azure"),
        ("worse", "log", "azure"),
    ]


def test_failed_delivery_records_nothing(tmp_path, monkeypatch):
    class Broken(Recorder):
        async def send(self, session, events, held=()):
            raise watch.DeliveryError("nope")

    scus = [
        (
            "azure",
            status(indicator=MAJOR, ongoing=[incident("Outage in South Central US")]),
        )
    ]
    with pytest.raises(watch.DeliveryError):
        run_watch(tmp_path, monkeypatch, scus, WORKDAY, Broken())
    assert not (tmp_path / ".gwen-history.sqlite").exists()
    assert not (tmp_path / "state.json").exists()


# --- config -----------------------------------------------------------------


def test_config_reads_rules_and_schedule(tmp_path):
    cfg = config.load(
        write(
            tmp_path,
            """
[watch]
default_priority = 2
work_hours = "Mon-Thu 07:30-16:00"
timezone = "America/Chicago"
history = "data/history.sqlite"

[[watch.rule]]
target = "azure/scus"
priority = 1
failover = ["azure/ncus"]
""",
        )
    )
    p = cfg.watch.policy
    assert p.default_priority == 2
    assert p.rules == [
        policy.Rule(
            Target("azure", "southcentralus"), 1, (Target("azure", "northcentralus"),)
        )
    ]
    assert p.hours.days == {0, 1, 2, 3}
    assert cfg.watch.history == tmp_path / "data" / "history.sqlite"


@pytest.mark.parametrize(
    "text,complaint",
    [
        ('[[watch.rule]]\ntarget = "azure/nowhere"', "gwen regions azure"),
        ("[[watch.rule]]\npriority = 1", "needs a target"),
        ('[[watch.rule]]\ntarget = "aws"\npriority = 5', "1, 2 or 3"),
        ("[watch]\ndefault_priority = 0", "1, 2 or 3"),
        ('[watch]\nwork_hours = "always"', "Mon-Fri"),
        ('[watch]\ntimezone = "Nowhere/Land"', "timezone"),
    ],
)
def test_bad_policy_config(tmp_path, text, complaint):
    with pytest.raises(config.ConfigError, match=complaint):
        config.load(write(tmp_path, text))


# --- rendering --------------------------------------------------------------


def test_telegram_shows_targets_and_held_section():
    now = [
        watch.Event(
            "Azure",
            "incident",
            "",
            "https://a/1",
            title="Outage",
            level=MAJOR,
            targets=["azure/southcentralus"],
        )
    ]
    held = [
        watch.Event(
            "Azure",
            "incident",
            "",
            title="Latency",
            level=MINOR,
            seen="2026-10-11T03:00:00+00:00",
        )
    ]
    text = watch.telegram_html(now, held=held)
    assert '🆕 <a href="https://a/1">Outage</a> · <i>azure/southcentralus</i>' in text
    assert "<b>While you were away</b> · 1 change since" in text
    assert (
        text.index("Outage") < text.index("While you were away") < text.index("Latency")
    )


def test_telegram_held_only_message():
    held = [watch.Event("Azure", "incident", "", title="Latency", level=MINOR)]
    assert watch.telegram_html([], held=held).startswith(
        "<b>GWEN</b> · 1 change while you were away"
    )


def test_console_groups_by_route(capsys):
    events = [
        watch.Event("Azure", "incident", "new incident: Outage", priority=1),
        watch.Event("Azure", "incident", "new incident: [x] Latency", priority=2),
        watch.Event("Azure", "incident", "new incident: Noise", priority=3),
    ]
    result = watch.Run(watch.route(events, False), [], [], False)
    cli.show_run(result, dry_run=False)
    out = capsys.readouterr().out
    assert "Sent now (1)" in out and "Held for work hours (1)" in out
    assert "History only (priority 3) (1)" in out
    assert "[x] Latency" in out, "vendor text must not be read as console markup"
