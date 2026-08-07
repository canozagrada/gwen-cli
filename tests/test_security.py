"""Bounds on what a status feed can do to us.

These feeds are third-party and unauthenticated, so a hostile or simply broken
response should not be able to hang the CLI, exhaust memory, or read local files.

The transport is exercised with a stand-in response rather than a real HTTP
server -- there is no server anywhere in this project, and there is no reason
for the tests to start one.
"""

from __future__ import annotations

import aiohttp
import pytest
from defusedxml import EntitiesForbidden
from defusedxml.ElementTree import fromstring

from conftest import run

from gwen_cli import providers

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<rss><channel><title>&lol3;</title></channel></rss>"""

EXTERNAL_ENTITY = """<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<rss><channel><title>&x;</title></channel></rss>"""


class Body:
    """Stands in for `response.content`, recording whether it was read."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.was_read = False

    async def iter_chunked(self, size):
        self.was_read = True
        for chunk in self.chunks:
            yield chunk


class Response:
    def __init__(self, chunks=(), content_length=None, status=200):
        self.content = Body(chunks)
        self.content_length = content_length
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                None, (), status=self.status, message="upstream error"
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Session:
    """Minimal stand-in for `aiohttp.ClientSession` as `_read` uses it."""

    def __init__(self, response):
        self.response = response

    def get(self, url, **kwargs):
        return self.response


def read(response):
    return run(providers._read(Session(response), "https://status.example/feed"))


def test_entity_expansion_is_blocked():
    with pytest.raises(EntitiesForbidden):
        fromstring(BILLION_LAUGHS)


def test_external_entities_are_blocked():
    with pytest.raises(EntitiesForbidden):
        fromstring(EXTERNAL_ENTITY)


def test_xml_bomb_in_a_feed_reports_unknown(stub_feeds):
    """End to end: a hostile feed degrades that provider, nothing more."""
    stub_feeds({"status/feed": BILLION_LAUGHS.encode()})

    result = run(providers._fetch_one(None, providers.AzureProvider(), 0))

    assert result.indicator == providers.UNKNOWN
    assert result.error


def test_a_normal_response_is_read_whole():
    body = [b"hello ", b"world"]

    assert read(Response(body, content_length=11)) == b"hello world"


def test_a_response_that_streams_past_the_cap_is_cut_off():
    """A feed that never stops sending must not be read into memory forever."""
    endless = (b"x" * 65536 for _ in range((providers._MAX_BYTES // 65536) + 8))

    with pytest.raises(ValueError, match="exceeded"):
        read(Response(endless))


def test_an_oversized_content_length_is_refused_without_reading():
    response = Response([b"x"], content_length=providers._MAX_BYTES + 1)

    with pytest.raises(ValueError, match="too large"):
        read(response)

    assert not response.content.was_read, "body should be rejected before download"


def test_http_errors_are_not_treated_as_data():
    with pytest.raises(aiohttp.ClientResponseError):
        read(Response([b"upstream down"], status=503))


def test_requests_are_time_bounded():
    assert providers._TIMEOUT.total is not None
    assert providers._TIMEOUT.total <= 60
    assert providers._TIMEOUT.connect is not None


def test_requests_identify_themselves():
    assert "gwen-cli" in providers._USER_AGENT


def test_all_feeds_are_https():
    """Status data is unauthenticated; at least keep it authenticated in transit."""
    urls = []
    for provider in providers.PROVIDERS.values():
        if isinstance(provider, providers.StatuspageProvider):
            urls.append(provider.base_url)
        for attribute in ("URL", "CURRENT", "HISTORY", "SITE"):
            value = getattr(provider, attribute, None)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)

    assert urls, "expected to find provider URLs to check"
    for url in urls:
        assert url.startswith("https://"), f"{url} is not HTTPS"
