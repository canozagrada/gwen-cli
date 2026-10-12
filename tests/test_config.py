"""`gwen.toml`: which providers to cover, and extra Statuspage vendors."""

from __future__ import annotations

import pytest

from gwen_cli import cli, config, providers

from conftest import load


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Config registers providers globally; keep each test's additions local."""
    monkeypatch.setattr(providers, "PROVIDERS", dict(providers.PROVIDERS))


def write(tmp_path, text: str):
    path = tmp_path / "gwen.toml"
    path.write_text(text, encoding="utf-8")
    return path


def invoke(monkeypatch, *argv) -> int:
    monkeypatch.setattr("sys.argv", ["gwen", *argv])
    return cli.main()


def test_no_config_file_means_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loaded = config.load()
    assert loaded.path is None
    assert loaded.providers is None


def test_config_selects_providers_and_registers_statuspage(tmp_path):
    path = write(
        tmp_path,
        """
providers = ["aws", "twilio"]

[[statuspage]]
key = "twilio"
label = "Twilio"
url = "https://status.twilio.com"
""",
    )
    loaded = config.load(path)

    assert loaded.providers == ["aws", "twilio"]
    assert providers.resolve("twilio").label == "Twilio"


def test_sections_from_older_versions_are_ignored(tmp_path):
    """Configs written for the removed `gwen watch` still load."""
    loaded = config.load(
        write(
            tmp_path,
            'providers = ["aws"]\n[watch]\nwork_hours = "x"\n[filters.aws]\nmatch = ["y"]\n',
        )
    )
    assert loaded.providers == ["aws"]


@pytest.mark.parametrize(
    "text,complaint",
    [
        ('providers = ["nope"]', "Unknown provider"),
        ('providers = "aws"', "list of strs"),
        ('[[statuspage]]\nkey = "x"', "missing url"),
        ('[[statuspage]]\nkey = "x"\nurl = "http://insecure.example"', "https://"),
        ('[[statuspage]]\nkey = "aws"\nurl = "https://x.example"', "built in"),
        ("providers = [", "gwen.toml"),
    ],
)
def test_bad_config_is_rejected_with_a_reason(tmp_path, text, complaint):
    with pytest.raises(config.ConfigError, match=complaint):
        config.load(write(tmp_path, text))


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(config.ConfigError, match="not found"):
        config.load(tmp_path / "absent.toml")


def test_bad_config_exits_with_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'providers = ["nope"]')
    assert invoke(monkeypatch, "status") == 2


def test_status_uses_the_configured_providers(tmp_path, monkeypatch, stub_feeds, capsys):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'providers = ["github"]\n')
    feeds = stub_feeds({"summary.json": load("statuspage_summary.json")})

    assert invoke(monkeypatch, "status") == 0
    assert all("githubstatus" in url for url in feeds.requested)
    assert "GitHub" in capsys.readouterr().out
