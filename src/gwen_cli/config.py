"""Load `gwen.toml`: the services you depend on.

A config file is optional. Without one, every command covers every built-in
provider. With one, it narrows the default provider list and adds vendors
that run Statuspage.

    providers = ["cloudflare", "aws", "github", "twilio"]

    [[statuspage]]
    key = "twilio"
    label = "Twilio"
    url = "https://status.twilio.com"
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

from . import providers

DEFAULT_PATH = pathlib.Path("gwen.toml")


class ConfigError(ValueError):
    """The config file exists but cannot be used."""


@dataclass
class Config:
    path: pathlib.Path | None = None
    providers: list[str] | None = None


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

    return Config(path=path, providers=selected)


def _list(data: dict, key: str, kind: type) -> list:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, kind) for item in value):
        raise ConfigError(f"{key!r} must be a list of {kind.__name__}s")
    return value
