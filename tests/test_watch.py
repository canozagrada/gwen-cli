"""`gwen.toml` and `gwen watch`: what counts as a change, and when it is sent."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from aiohttp import web
from conftest import load, run

from gwen_cli import cli, config, providers, watch
from gwen_cli.providers import (
    MAJOR,
    MINOR,
    OK,
    UNKNOWN,
    Component,
    Incident,
    ProviderStatus,
)

STARTED = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Config registers providers globally; keep each test's additions local."""
    monkeypatch.setattr(providers, "PROVIDERS", dict(providers.PROVIDERS))


def write(tmp_path, text: str):
    path = tmp_path / "gwen.toml"
    path.write_text(text, encoding="utf-8")
    return path


def status(
    name="AWS", indicator=OK, ongoing=(), degraded=(), error=None
) -> ProviderStatus:
    return ProviderStatus(
        name=name,
        indicator=indicator,
        ongoing=list(ongoing),
        degraded=list(degraded),
        error=error,
    )


def incident(name: str, *components: str) -> Incident:
    return Incident(
        name=name,
        started_at=STARTED,
        url="https://status.example/i",
        components=list(components),
    )


def step(results, previous=None, filters=None, unreadable_after=2):
    return watch.evaluate(results, previous or {}, filters or {}, unreadable_after)


# --- config -----------------------------------------------------------------


def test_no_config_file_means_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loaded = config.load()
    assert loaded.path is None
    assert loaded.providers is None
    assert loaded.filters == {}


def test_config_selects_providers_and_registers_statuspage(tmp_path):
    path = write(
        tmp_path,
        """
providers = ["aws", "twilio"]

[[statuspage]]
key = "twilio"
label = "Twilio"
url = "https://status.twilio.com"

[filters.AWS]
match = ["US-East-1"]

[watch]
state = "state/gwen.json"
unreadable_after = 3
""",
    )
    loaded = config.load(path)

    assert loaded.providers == ["aws", "twilio"]
    assert providers.resolve("twilio").label == "Twilio"
    assert loaded.filters == {"aws": ["us-east-1"]}
    assert loaded.watch.state == tmp_path / "state" / "gwen.json"
    assert loaded.watch.unreadable_after == 3


@pytest.mark.parametrize(
    "text,complaint",
    [
        ('providers = ["nope"]', "Unknown provider"),
        ('providers = "aws"', "list of strs"),
        ('[[statuspage]]\nkey = "x"', "missing url"),
        ('[[statuspage]]\nkey = "x"\nurl = "http://insecure.example"', "https://"),
        ('[[statuspage]]\nkey = "aws"\nurl = "https://x.example"', "built in"),
        ("[watch]\nunreadable_after = 0", "positive integer"),
        ("providers = [", "gwen.toml"),
    ],
)
def test_bad_config_is_rejected_with_a_reason(tmp_path, text, complaint):
    with pytest.raises(config.ConfigError, match=complaint):
        config.load(write(tmp_path, text))


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(config.ConfigError, match="not found"):
        config.load(tmp_path / "absent.toml")


# --- change detection -------------------------------------------------------


def test_first_run_reports_existing_problems():
    events, _ = step(
        [("aws", status(indicator=MAJOR, ongoing=[incident("EC2 errors")]))]
    )
    kinds = [e.kind for e in events]
    assert kinds == ["incident", "worse"]


def test_first_run_with_everything_healthy_is_quiet():
    events, _ = step([("aws", status())])
    assert events == []


def test_unchanged_state_is_quiet():
    results = [("aws", status(indicator=MAJOR, ongoing=[incident("EC2 errors")]))]
    _, state = step(results)
    events, _ = step(results, state)
    assert events == []


def test_resolution_is_reported():
    _, state = step(
        [("aws", status(indicator=MAJOR, ongoing=[incident("EC2 errors")]))]
    )
    events, _ = step([("aws", status())], state)
    assert [e.kind for e in events] == ["resolved", "better"]
    assert "EC2 errors" in events[0].summary


def test_one_failed_read_is_not_reported_and_keeps_incidents():
    """A single timeout must neither page anyone nor 'resolve' an incident."""
    _, state = step(
        [("aws", status(indicator=MAJOR, ongoing=[incident("EC2 errors")]))]
    )

    events, state = step([("aws", status(indicator=UNKNOWN, error="timed out"))], state)
    assert events == []

    events, _ = step(
        [("aws", status(indicator=MAJOR, ongoing=[incident("EC2 errors")]))], state
    )
    assert events == []


def test_repeated_failed_reads_are_reported_once_then_recovery():
    failed = [("azure", status("Azure", UNKNOWN, error="feed last rebuilt 2026-01-01"))]

    events, state = step(failed)
    assert events == []
    events, state = step(failed, state)
    assert [e.kind for e in events] == ["unreadable"]
    assert "2026-01-01" in events[0].summary
    events, state = step(failed, state)
    assert events == [], "already reported; do not repeat every run"

    events, _ = step([("azure", status("Azure"))], state)
    assert [e.kind for e in events] == ["readable"]


def test_filters_ignore_unrelated_incidents():
    results = [
        (
            "aws",
            status(
                indicator=MAJOR,
                ongoing=[incident("Lambda errors (ap-south-1)", "Lambda")],
            ),
        )
    ]
    events, state = step(results, filters={"aws": ["us-east-1"]})
    assert events == []
    assert state["aws"]["level"] == OK


def test_filters_match_incident_components():
    results = [
        (
            "aws",
            status(indicator=MINOR, ongoing=[incident("Elevated errors", "us-east-1")]),
        )
    ]
    events, _ = step(results, filters={"aws": ["us-east-1"]})
    assert [e.kind for e in events] == ["incident", "worse"]


def test_components_are_tracked_only_when_filtered():
    degraded = [
        Component("Frankfurt, Germany - (FRA)", "partial_outage"),
        Component("Lima, Peru - (LIM)", "partial_outage"),
    ]
    flare = [("cloudflare", status("Cloudflare", MINOR, degraded=degraded))]

    unfiltered, _ = step(flare)
    assert [e.kind for e in unfiltered] == ["worse"]

    filtered, state = step(flare, filters={"cloudflare": ["fra"]})
    assert [e.kind for e in filtered] == ["degraded", "worse"]
    assert "Frankfurt" in filtered[0].summary and "Lima" not in filtered[0].summary

    events, _ = step(
        [("cloudflare", status("Cloudflare", MINOR))], state, {"cloudflare": ["fra"]}
    )
    assert [e.kind for e in events] == ["recovered", "better"]


def test_message_and_payload_shape():
    events = [
        watch.Event("AWS", "incident", "new incident: EC2 errors", "https://x.example")
    ]
    body = watch.payload(events)
    assert (
        body["text"]
        == "gwen: 1 change\n- AWS: new incident: EC2 errors (https://x.example)"
    )
    assert body["events"][0]["kind"] == "incident"
    json.dumps(body)


# --- state file -------------------------------------------------------------


def test_state_round_trip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    watch.save_state(path, {"aws": {"level": OK}})
    assert watch.load_state(path) == {"aws": {"level": OK}}


@pytest.mark.parametrize(
    "content", ["not json", '{"version": 999, "providers": {"aws": {}}}', "[]"]
)
def test_unusable_state_starts_fresh(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    assert watch.load_state(path) == {}


# --- delivery ---------------------------------------------------------------


async def _serve(status_code: int, received: list):
    async def handle(request):
        received.append(await request.json())
        return web.Response(
            status=status_code, text="nope" if status_code >= 400 else "ok"
        )

    app = web.Application()
    app.router.add_post("/hook", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/hook"


AWS_DOWN = json.dumps(
    [
        {
            "service_name": "EC2",
            "summary": "Increased error rates",
            "region_name": "us-east-1",
            "date": "1759320000",
            "status": "2",
        }
    ]
).encode("utf-16")


def test_run_once_posts_then_saves_state(tmp_path, stub_feeds):
    stub_feeds({"currentevents": AWS_DOWN})
    state_path = tmp_path / "state.json"
    received: list = []

    async def scenario():
        runner, url = await _serve(200, received)
        try:
            first = await watch.run_once(config.Config(), ["aws"], state_path, url)
            second = await watch.run_once(config.Config(), ["aws"], state_path, url)
        finally:
            await runner.cleanup()
        return first, second

    (events, _), (again, _) = run(scenario())
    assert [e.kind for e in events] == ["incident", "worse"]
    assert again == []
    assert len(received) == 1
    assert "EC2: Increased error rates (us-east-1)" in received[0]["text"]


def test_failed_delivery_does_not_save_state(tmp_path, stub_feeds):
    stub_feeds({"currentevents": AWS_DOWN})
    state_path = tmp_path / "state.json"
    received: list = []

    async def scenario():
        runner, url = await _serve(500, received)
        try:
            await watch.run_once(config.Config(), ["aws"], state_path, url)
        finally:
            await runner.cleanup()

    with pytest.raises(RuntimeError, match="HTTP 500"):
        run(scenario())
    assert not state_path.exists(), "undelivered changes must be retried next run"


# --- command line -----------------------------------------------------------


def invoke(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["gwen", *argv])
    return cli.main()


def test_watch_requires_a_webhook(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GWEN_WEBHOOK", raising=False)
    assert invoke(monkeypatch, "watch") == 2


def test_watch_dry_run_uses_config(tmp_path, monkeypatch, stub_feeds, capsys):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'providers = ["github"]\n[watch]\nstate = "s.json"\n')
    stub_feeds({"summary.json": load("statuspage_summary.json")})

    assert invoke(monkeypatch, "watch", "--dry-run") == 0

    out = capsys.readouterr().out
    assert "Dry run" in out or "No changes" in out
    assert (tmp_path / "s.json").exists()
    assert set(watch.load_state(tmp_path / "s.json")) == {"github"}


def test_bad_config_exits_with_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'providers = ["nope"]')
    assert invoke(monkeypatch, "status") == 2


def test_interval_below_a_minute_is_rejected(monkeypatch):
    with pytest.raises(SystemExit):
        invoke(monkeypatch, "watch", "--dry-run", "--interval", "5")
