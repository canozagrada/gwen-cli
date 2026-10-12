# AGENTS.md

GWEN (`gwen`) is a command-line monitor that reads the public status feeds of several cloud and SaaS vendors and prints one summary. Users are developers and operators, often running it in health checks, so the exit code is part of the interface: 0 when every feed was read, 1 when any feed could not be read, 2 for bad arguments. The README covers user-facing behaviour.

## The rule everything else follows

A false "all clear" is the worst thing this tool can produce. A previous version reported AWS and Azure as healthy for months because their endpoints moved and the parsers returned empty results that rendered as "operational". So:

- A feed that cannot be read becomes `UNKNOWN` with an `error` string, never `OK`. `_fetch_one` in `providers.py` does this conversion; parsers should raise (`ValueError`, `KeyError`, `TypeError`, XML `ParseError`) on unexpected shapes rather than return empty data. If a new failure mode raises something else, add it there, because an uncaught exception takes down the whole run instead of one provider.
- When a vendor does not publish something (history, maintenance, components), the provider sets the matching `supports_*` flag to False and the CLI shows `--`. An empty list on its own must mean "checked, nothing found".
- An empty feed is only good news if the feed is demonstrably still maintained; see the `lastBuildDate` staleness check in `AzureProvider`.

`tests/test_resilience.py` encodes these guarantees for every provider type.

## Architecture

`src/gwen_cli/providers.py` holds one `Provider` subclass per feed type and the `PROVIDERS` registry. Each provider implements `async fetch(session, days) -> ProviderStatus` and builds its result with `self.status(...)`, which copies the class's `supports_*` flags into the result. `days == 0` means the caller did not ask for history, and providers skip the extra request in that case. All HTTP goes through `_read` (or `_read_json`); `gather()` fetches every selected provider concurrently over one `aiohttp` session.

Adding a provider: a site running Atlassian Statuspage v2 is one `StatuspageProvider(key, label, base_url)` line in `PROVIDERS`. Anything else is a `Provider` subclass with `key`, `label`, `source`, accurate `supports_*` flags, and feed URLs as class attributes named `URL`, `CURRENT`, `HISTORY` or `SITE` (the HTTPS test discovers URLs by those names). Add a recorded fixture, parsing tests, a row in `CASES` in `test_resilience.py`, and a shape check in `test_live.py`. Also update the provider table and list in the README.

`src/gwen_cli/regions.py` groups components and maintenance windows by free-text keyword matching. It is a display convenience only. `REGIONS` is checked in order and the first match wins, so a more specific region has to come before one it could be confused with.

`src/gwen_cli/cli.py` is argparse plus `rich` output and should not contain vendor-specific logic.

The version string lives in both `pyproject.toml` and `src/gwen_cli/__init__.py` (it feeds the User-Agent), so change both together.

## Commands

The project uses uv; `uv run` builds `.venv` from `uv.lock` on first use.

- `uv run gwen status` runs the CLI from source.
- `uv run pytest` runs the offline suite. `pyproject.toml` sets `addopts = "-m 'not live'"`, so live tests are excluded by default.
- `uv run pytest -m live` runs only the live tests, which make real requests to every vendor's endpoints and depend on their uptime. Run them when you change a URL or parser or want to confirm a feed's shape, not as a routine check.

- `uv run ruff check` lints (rules E, W, F, I, B, UP, SIM, RUF; line length 100). `uv run ruff check --fix` applies the safe fixes.
- `uv run ruff format` formats; CI runs `uv run ruff format --check`. Hand-aligned data tables, such as `REGIONS` in `regions.py`, sit between `# fmt: off` / `# fmt: on`.
- `uv run mypy` type-checks `src/` (configured under `[tool.mypy]`).

Ruff and mypy are configured in `pyproject.toml`. Dev dependencies are declared twice in `pyproject.toml` (`[dependency-groups]` for uv, `[project.optional-dependencies]` for `pip install -e ".[dev]"`), and the two lists have to stay identical.

## Tests and fixtures

Offline tests never touch the network. The `stub_feeds` fixture in `tests/conftest.py` replaces `providers._read` and serves bytes by URL fragment. Any request it has no mapping for fails the test, which also catches accidental extra requests. Async code is driven with the `run()` helper (`asyncio.run`) because there is no async pytest plugin. Tests import helpers with `from conftest import ...`.

`tests/test_e2e.py` runs the installed `gwen` executable as a subprocess, so it checks the entry point, argument parsing, exit codes and real HTTP/TLS. A subprocess cannot see `stub_feeds`, so the offline cases serve `tests/fixtures/` from a local HTTPS server (a throwaway CA from `trustme`, trusted through `SSL_CERT_FILE`) and point a `[[statuspage]]` provider in a temporary `gwen.toml` at it. Built-in providers have fixed URLs, so their CLI path is covered only by the `live` cases. Set `GWEN_BIN` to run these tests against another `gwen`, such as one installed from a built wheel.

Files in `tests/fixtures/` are real vendor payloads, trimmed but otherwise in their original shape. `.gitattributes` marks them `-text`, so line endings and bytes stay exactly as recorded. Do not reformat them by hand; re-record them from the live endpoint instead. For small edge cases, an inline payload in the test reads better than a new fixture file.

Fixtures carry fixed timestamps, so an assertion that depends on "now" will rot as the fixture ages. Build payloads relative to `datetime.now(timezone.utc)`, or rewrite the timestamp the way `_azure_with_build_date` in `test_parsing.py` does.

## Security conventions

The feeds are third-party and unauthenticated, so the code treats responses as hostile input. `tests/test_security.py` enforces:

- XML is parsed only with `defusedxml` (`from defusedxml.ElementTree import fromstring`), never the standard library parser, to block entity expansion and external entities that could read local files.
- Every response is read through `_read`, which rejects an oversized `Content-Length` before downloading and stops a streamed body at `_MAX_BYTES`, so a misbehaving feed cannot exhaust memory.
- `_TIMEOUT` sets both total and connect limits, so a stalled feed cannot hang the CLI.
- HTTP error statuses raise instead of being parsed as data.
- Requests send `_USER_AGENT`, which identifies gwen-cli.
- Every feed URL is `https://`.
