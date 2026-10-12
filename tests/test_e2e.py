"""End-to-end checks of the installed `gwen` command, run as a subprocess.

The rest of the suite calls Python functions with `providers._read` stubbed
out. These run the real console-script entry point, so they also cover
packaging (the `[project.scripts]` entry), argument parsing, config loading,
aiohttp and TLS, rendering, and exit codes -- the interface health checks
depend on (0 every feed read, 1 a feed unreadable, 2 bad arguments).

A subprocess cannot see the `stub_feeds` monkeypatch, so the offline tests
serve `tests/fixtures/` from a local HTTPS server instead and point a
`[[statuspage]]` provider in `gwen.toml` at it. Config only accepts https://
URLs, so the server uses a throwaway CA from `trustme`, which the child
process trusts through `SSL_CERT_FILE`. Built-in providers have fixed URLs and
are covered offline by the in-process tests and online by the `live` ones
below.

Set `GWEN_BIN` to test a different `gwen` executable, for example one
installed from a built wheel.
"""

from __future__ import annotations

import http.server
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import sysconfig
import threading

import pytest

from gwen_cli import providers

from conftest import FIXTURES

TIMEOUT = 60


def _gwen_bin() -> str:
    override = os.environ.get("GWEN_BIN")
    if override:
        return override
    name = "gwen.exe" if sys.platform == "win32" else "gwen"
    for folder in (sysconfig.get_path("scripts"), str(pathlib.Path(sys.executable).parent)):
        candidate = pathlib.Path(folder) / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("gwen")
    if found:
        return found
    pytest.fail("could not find the installed `gwen` executable; run `uv sync` or set GWEN_BIN")


def gwen(*args: str, cwd: pathlib.Path, env: dict[str, str] | None = None):
    """Run `gwen *args` in *cwd* and return the CompletedProcess."""
    child_env = {
        **os.environ,
        # Wide, plain, UTF-8 output so assertions see whole table cells.
        "COLUMNS": "200",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        **(env or {}),
    }
    return subprocess.run(
        [_gwen_bin(), *args],
        cwd=cwd,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        check=False,
    )


# --- offline: arguments, help and listings -----------------------------------


def test_help_lists_every_command(tmp_path):
    result = gwen("--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    for command in ("status", "incidents", "maintenance", "regions", "providers"):
        assert command in result.stdout


def test_no_command_prints_help_and_succeeds(tmp_path):
    result = gwen(cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "usage: gwen" in result.stdout


def test_providers_lists_the_registry(tmp_path):
    result = gwen("providers", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    for key in providers.PROVIDERS:
        assert key in result.stdout


def test_regions_lists_a_catalog(tmp_path):
    result = gwen("regions", "azure", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "azure/southcentralus" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("status", "nosuchvendor"),
        ("status", "azure/atlantis"),
        ("status", "--days", "many"),
        ("frobnicate",),
        ("--config", "missing.toml", "status"),
    ],
    ids=["unknown-provider", "unknown-region", "bad-int", "unknown-command", "missing-config"],
)
def test_bad_arguments_exit_2(tmp_path, args):
    result = gwen(*args, cwd=tmp_path)
    assert result.returncode == 2, (result.stdout, result.stderr)


def test_invalid_config_exits_2(tmp_path):
    (tmp_path / "gwen.toml").write_text('providers = ["nosuchvendor"]\n', encoding="utf-8")
    result = gwen("status", cwd=tmp_path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "nosuchvendor" in result.stdout


# --- offline: real HTTP against recorded fixtures ----------------------------

ROUTES = {
    "/ok/api/v2/summary.json": "statuspage_summary.json",
    "/ok/api/v2/incidents.json": "statuspage_incidents.json",
}


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        name = ROUTES.get(self.path)
        if name is None:
            # Covers /broken/...: an error status must become UNKNOWN, not OK.
            self.send_error(500 if self.path.startswith("/broken/") else 404)
            return
        body = (FIXTURES / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def fixture_server(tmp_path_factory):
    """An HTTPS server for `tests/fixtures`, and the env to trust it."""
    trustme = pytest.importorskip("trustme")
    ca = trustme.CA()
    cert = ca.issue_cert("127.0.0.1")
    folder = tmp_path_factory.mktemp("tls")
    ca_file = folder / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_file))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert.configure_cert(context)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"https://127.0.0.1:{server.server_address[1]}"
        yield base, {"SSL_CERT_FILE": str(ca_file), "SSL_CERT_DIR": ""}
    finally:
        server.shutdown()
        server.server_close()


def _config(tmp_path: pathlib.Path, base: str, *keys: str) -> None:
    entries = {
        "fixtureok": f"{base}/ok",
        "fixturebroken": f"{base}/broken",
    }
    lines = [f"providers = {list(keys)!r}".replace("'", '"'), ""]
    for key in keys:
        lines += ["[[statuspage]]", f'key = "{key}"', f'url = "{entries[key]}"', ""]
    (tmp_path / "gwen.toml").write_text("\n".join(lines), encoding="utf-8")


def test_status_reads_a_feed_over_https(tmp_path, fixture_server):
    base, env = fixture_server
    _config(tmp_path, base, "fixtureok")

    result = gwen("status", cwd=tmp_path, env=env)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Fixtureok" in result.stdout
    # The recorded summary reports a minor outage; it must not read as OK.
    assert "MINOR" in result.stdout
    assert "UNKNOWN" not in result.stdout


def test_status_detail_for_one_provider(tmp_path, fixture_server):
    base, env = fixture_server
    _config(tmp_path, base, "fixtureok")

    result = gwen("status", "fixtureok", cwd=tmp_path, env=env)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Minor Service Outage" in result.stdout


def test_incidents_history_reads_second_endpoint(tmp_path, fixture_server):
    base, env = fixture_server
    _config(tmp_path, base, "fixtureok")

    result = gwen("incidents", "--show-recent", "--days", "36500", cwd=tmp_path, env=env)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "Web Analytics Configuration issues" in result.stdout


def test_unreadable_feed_is_unknown_and_exits_1(tmp_path, fixture_server):
    base, env = fixture_server
    _config(tmp_path, base, "fixtureok", "fixturebroken")

    result = gwen("status", cwd=tmp_path, env=env)

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "UNKNOWN" in result.stdout
    assert "Fixturebroken" in result.stdout
    # The healthy provider is still reported alongside the broken one.
    assert "MINOR" in result.stdout


def test_untrusted_certificate_is_not_accepted(tmp_path, fixture_server):
    """Without the test CA, TLS verification must fail rather than pass silently."""
    base, _ = fixture_server
    _config(tmp_path, base, "fixtureok")

    result = gwen("status", cwd=tmp_path)

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "UNKNOWN" in result.stdout
    assert "certificate verify failed" in " ".join(result.stdout.split()).lower()


# --- live: the real vendor feeds ---------------------------------------------


@pytest.mark.live
def test_live_status_reads_every_feed(tmp_path):
    result = gwen("status", cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "UNKNOWN" not in result.stdout
    for provider in providers.PROVIDERS.values():
        assert provider.label in result.stdout


@pytest.mark.live
def test_live_region_detail(tmp_path):
    result = gwen("status", "azure/scus", cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "southcentralus" in result.stdout


@pytest.mark.live
def test_live_incident_history(tmp_path):
    result = gwen("incidents", "--show-recent", "--days", "7", cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
