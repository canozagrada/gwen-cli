# GWEN

**G**lobal **W**atch **E**ngine for **N**etwork services — a command-line monitor for public cloud status feeds.

GWEN checks Cloudflare, AWS, Azure, GCP, GitHub, Datadog, and Atlassian concurrently and prints a single summary. It reads only public status endpoints, so there are no credentials to configure and nothing to run in the background.

```
$ gwen status
                             Cloud Service Status
+----------------------------------------------------------------------------+
| Service    | Status | Components  | Incidents | Maintenance | Updated      |
|------------+--------+-------------+-----------+-------------+--------------|
| Cloudflare | MINOR  | 52 degraded |         0 |          14 | 08-07 02:48Z |
| AWS        | MAJOR  | --          |         2 |          -- | 08-07 03:59Z |
| Azure      | OK     | --          |         0 |          -- | 08-07 03:59Z |
| GCP        | OK     | --          |         0 |          -- | 08-07 03:59Z |
| GitHub     | OK     | all OK      |         0 |           0 | 08-07 02:48Z |
| Datadog    | OK     | all OK      |         0 |           0 | 08-06 22:48Z |
| Atlassian  | OK     | all OK      |         0 |           0 | 08-07 02:48Z |
+----------------------------------------------------------------------------+
```

## Install

Requires Python 3.10 or newer.

With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/marcodepumper/gwen-cli.git
cd gwen-cli
uv run gwen status
```

`uv run` creates the environment from `uv.lock` on first use, so there is no separate install step. To get `gwen` on your PATH as a standalone tool:

```bash
uv tool install .            # or: uv tool install --editable .
```

With pip:

```bash
git clone https://github.com/marcodepumper/gwen-cli.git
cd gwen-cli
pip install -e .
```

Either way you get one command, `gwen`.

## Usage

```bash
gwen status                       # summary of all providers
gwen status cloudflare            # detail, including degraded components by region
gwen incidents                    # ongoing incidents only
gwen incidents --show-recent      # include resolved, last 14 days
gwen incidents --days 30 --show-recent
gwen maintenance                  # upcoming windows, grouped by region
gwen providers                    # what each provider publishes
```

Any command takes an optional provider name: `cloudflare`, `aws`, `azure`, `gcp`, `github`, `datadog`, `atlassian`.

**Exit codes** — `0` all feeds read successfully, `1` at least one feed could not be read, `2` bad arguments. This makes `gwen` usable in a health check:

```bash
gwen status >/dev/null || echo "a status feed is unreachable"
```

## What each provider actually publishes

Providers expose different things. GWEN prints `--` where a provider publishes nothing, rather than a `0` that would read as "checked, nothing found".

| Provider   | Source        | Incident history | Maintenance | Components |
|------------|---------------|------------------|-------------|------------|
| Cloudflare | Statuspage v2 | yes              | yes         | yes        |
| GitHub     | Statuspage v2 | yes              | yes         | yes        |
| Datadog    | Statuspage v2 | yes              | yes         | yes        |
| Atlassian  | Statuspage v2 | yes              | yes         | --         |
| AWS        | AWS Health    | yes              | --          | --         |
| GCP        | Cloud Status  | yes              | --          | --         |
| Azure      | Status RSS    | --               | --          | --         |

Azure's RSS feed carries only currently-active issues; there is no public history or maintenance calendar behind it. Atlassian runs Statuspage but publishes no component list, so component health is detected per response rather than assumed from the platform.

## Design

A status tool that reports a false "all clear" is worse than no tool, so failures are never silent:

- A feed that cannot be read reports `UNKNOWN` with the reason, never `operational`.
- One provider failing does not affect the others — each is isolated.
- Azure's feed is checked against its own `lastBuildDate`; a feed that has stopped being rebuilt is treated as unavailable rather than as good news. An earlier version of this tool reported AWS and Azure as permanently healthy because both feeds had moved and the empty result was indistinguishable from "no incidents".

Outbound requests are bounded in time (20s) and size (8 MB), and XML is parsed with `defusedxml` to block entity-expansion attacks.

## Layout

```
src/gwen_cli/
├── cli.py          # argument parsing and rich-formatted output
├── providers.py    # one fetcher per vendor, normalised to a common shape
└── regions.py      # geographic grouping for components and maintenance
```

`providers.gather()` opens a single connection pool and fetches every provider concurrently. Each returns a `ProviderStatus`, so `cli.py` never needs to know how a given vendor publishes its data.

## Tests

```bash
uv run pytest             # offline, runs in well under a second
uv run pytest -m live     # also check the real endpoints (needs network)
```

Or with pip:

```bash
pip install -e ".[dev]"
pytest
pytest -m live
```

The default suite runs against payloads recorded from each vendor in `tests/fixtures/`, so it needs no network and is deterministic.

The `live` tests are the ones that matter for the failure this tool has actually had. Recorded fixtures prove the parsers handle the shape the feeds *had*; the live tests prove the feeds still have that shape. AWS and Azure both drifted into reporting a permanent all-clear because the code kept working correctly against data that had stopped arriving. Worth running on a schedule rather than on every commit.

### Adding a provider

If it runs Atlassian Statuspage, add one line to `PROVIDERS` in `providers.py`:

```python
StatuspageProvider("fastly", "Fastly", "https://status.fastly.com"),
```

Otherwise subclass `Provider`, implement `fetch()`, return `self.status(...)`, and set `supports_history` / `supports_maintenance` / `supports_components` to match what the feed really offers.

## License

MIT
