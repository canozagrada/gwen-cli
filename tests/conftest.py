"""Shared test helpers.

Tests never touch the network. `stub_feeds` swaps `providers._read` for a
lookup into `tests/fixtures/`, which holds real payloads recorded from each
vendor (trimmed, with long text truncated, but otherwise the genuine shape).
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from gwen_cli import providers

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    """Run a coroutine from a synchronous test, so no async plugin is needed."""
    return asyncio.run(coro)


class Feeds:
    """Serves recorded bytes by URL fragment instead of making requests."""

    def __init__(self, mapping: dict[str, bytes]):
        self.mapping = mapping
        self.requested: list[str] = []

    async def read(self, session, url: str) -> bytes:
        self.requested.append(url)
        for fragment, payload in self.mapping.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"test made an unexpected request: {url}")


@pytest.fixture
def stub_feeds(monkeypatch):
    """Return a factory that installs recorded responses for the test."""

    def install(mapping: dict[str, bytes]) -> Feeds:
        feeds = Feeds(mapping)
        monkeypatch.setattr(providers, "_read", feeds.read)
        return feeds

    return install
