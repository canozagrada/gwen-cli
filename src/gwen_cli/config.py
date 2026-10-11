"""Load `gwen.toml`: the services you depend on and where to send alerts.

A config file is optional. Without one, every command covers every built-in
provider, exactly as before. With one, it narrows the default provider list,
adds vendors that run Statuspage, and tells `gwen watch` which incidents and
components matter to you.

    providers = ["cloudflare", "aws", "github", "twilio"]

    [[statuspage]]
    key = "twilio"
    label = "Twilio"
    url = "https://status.twilio.com"

    [filters.aws]
    match = ["us-east-1", "eu-west-1"]

    [watch]
    state = ".gwen-state.json"
    unreadable_after = 2
    work_hours = "Mon-Fri 08:00-18:00"

    [[watch.rule]]
    target = "azure/scus"
    priority = 1
    failover = ["azure/ncus"]

The webhook URL is deliberately read from `--webhook` or `GWEN_WEBHOOK` as
well as `[watch] webhook`, and a Telegram bot token only from
`GWEN_TELEGRAM_TOKEN`, because both are secrets and the config file
is meant to be committed.
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from . import policy as policies
from . import providers

DEFAULT_PATH = pathlib.Path("gwen.toml")


class ConfigError(ValueError):
    """The config file exists but cannot be used."""


@dataclass
class WatchSettings:
    webhook: str | None = None
    #: Telegram chat to message. Not secret; the bot token is.
    telegram_chat: str | None = None
    state: pathlib.Path = pathlib.Path(".gwen-state.json")
    #: Consecutive failed reads before a feed is reported as unreadable, so a
    #: single timeout does not page anyone.
    unreadable_after: int = 2
    #: SQLite history. None means next to the state file.
    history: pathlib.Path | None = None
    #: Priorities per target and work hours. See `policy`.
    policy: policies.Policy = field(default_factory=policies.Policy)


@dataclass
class Config:
    path: pathlib.Path | None = None
    providers: list[str] | None = None
    #: Provider key -> lowercase substrings. An incident or degraded component
    #: only counts when its name or component list contains one of them.
    filters: dict[str, list[str]] = field(default_factory=dict)
    watch: WatchSettings = field(default_factory=WatchSettings)


def load(path: pathlib.Path | str | None = None) -> Config:
    """Read *path*, or `./gwen.toml` if it exists, or return an empty config.

    Extra Statuspage providers are registered as a side effect so that every
    command can use them by key.
    """
    if path is None:
        if not DEFAULT_PATH.is_file():
            return Config()
        path = DEFAULT_PATH
    path = pathlib.Path(path)

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None

    try:
        return _parse(data, path)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def _parse(data: dict, path: pathlib.Path) -> Config:
    for entry in _list(data, "statuspage", dict):
        missing = [name for name in ("key", "url") if not entry.get(name)]
        if missing:
            raise ConfigError(f"[[statuspage]] entry is missing {', '.join(missing)}")
        key = str(entry["key"]).strip().lower()
        url = str(entry["url"])
        if not url.startswith("https://"):
            raise ConfigError(f"statuspage {key!r}: url must start with https://")
        label = str(entry.get("label") or key.title())
        try:
            providers.register(providers.StatuspageProvider(key, label, url))
        except ValueError as exc:
            raise ConfigError(str(exc)) from None

    selected = None
    if "providers" in data:
        selected = [str(name) for name in _list(data, "providers", str)]
        for name in selected:
            try:
                providers.resolve(name)
            except KeyError as exc:
                raise ConfigError(exc.args[0]) from None

    filters: dict[str, list[str]] = {}
    for name, rule in _table(data, "filters").items():
        if not isinstance(rule, dict):
            raise ConfigError(f"[filters.{name}] must be a table")
        try:
            key = providers.resolve(name).key
        except KeyError as exc:
            raise ConfigError(exc.args[0]) from None
        terms = [str(term).lower() for term in _list(rule, "match", str)]
        if terms:
            filters[key] = terms

    section = _table(data, "watch")
    if "telegram_token" in section:
        raise ConfigError(
            "[watch] telegram_token is not read from the config file; "
            "set the GWEN_TELEGRAM_TOKEN environment variable instead"
        )
    chat = section.get("telegram_chat")
    if chat is not None and (isinstance(chat, bool) or not isinstance(chat, (str, int))):
        raise ConfigError("[watch] telegram_chat must be a chat id or @channel name")
    watch = WatchSettings(
        webhook=section.get("webhook") or None,
        telegram_chat=str(chat) if chat not in (None, "") else None,
    )
    if "state" in section:
        # Relative to the config file, so cron jobs don't depend on their cwd.
        watch.state = path.parent / str(section["state"])
    if "unreadable_after" in section:
        value = section["unreadable_after"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ConfigError("[watch] unreadable_after must be a positive integer")
        watch.unreadable_after = value
    if "history" in section:
        watch.history = path.parent / str(section["history"])

    try:
        watch.policy = _policy(section)
    except policies.PolicyError as exc:
        raise ConfigError(str(exc)) from None

    return Config(path=path, providers=selected, filters=filters, watch=watch)


def _policy(section: dict) -> policies.Policy:
    rules = policies.parse_rules(_list(section, "rule", dict))
    default = section.get("default_priority", policies.LOG)
    if default not in policies.PRIORITIES or isinstance(default, bool):
        raise ConfigError("[watch] default_priority must be 1, 2 or 3")
    zone = section.get("timezone")
    if zone is not None and not isinstance(zone, str):
        raise ConfigError("[watch] timezone must be a name such as 'America/Chicago'")
    hours = section.get("work_hours", policies.DEFAULT_HOURS)
    if not isinstance(hours, str):
        raise ConfigError("[watch] work_hours must look like 'Mon-Fri 08:00-18:00'")
    schedule = policies.parse_schedule(hours, zone)
    return policies.Policy(rules, default, schedule, explicit_default="default_priority" in section)


def _table(data: dict, key: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{key!r} must be a table")
    return value


def _list(data: dict, key: str, kind: type) -> list:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, kind) for item in value):
        raise ConfigError(f"{key!r} must be a list of {kind.__name__}s")
    return value
