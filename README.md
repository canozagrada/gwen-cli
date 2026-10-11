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
git clone https://github.com/canozagrada/gwen-cli.git
cd gwen-cli
uv run gwen status
```

`uv run` creates the environment from `uv.lock` on first use, so there is no separate install step. To get `gwen` on your PATH as a standalone tool:

```bash
uv tool install .            # or: uv tool install --editable .
```

With pip:

```bash
git clone https://github.com/canozagrada/gwen-cli.git
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

## Your dependencies: `gwen.toml`

Out of the box GWEN covers every built-in provider. A `gwen.toml` in the current directory (or `--config path`) narrows that to what you actually depend on, adds vendors that run Statuspage, and tells `gwen watch` which incidents matter. See [`gwen.example.toml`](gwen.example.toml):

```toml
providers = ["cloudflare", "aws", "github", "twilio"]

[[statuspage]]                 # any vendor on Atlassian Statuspage
key = "twilio"
label = "Twilio"
url = "https://status.twilio.com"

[filters.aws]                  # only incidents mentioning these count
match = ["us-east-1", "eu-west-1"]

[filters.cloudflare]           # filtered providers also get per-component alerts
match = ["(FRA)", "(AMS)"]

[watch]
state = ".gwen-state.json"     # relative to this file
unreadable_after = 2           # failed reads in a row before a feed is reported
telegram_chat = "987654321"    # bot token comes from GWEN_TELEGRAM_TOKEN
```

Every command respects `providers` and the extra Statuspage vendors. Filters only apply to `gwen watch`; `gwen status` still shows each provider's whole picture.

## Alerts: `gwen watch`

`gwen watch` compares the current state with the previous run and sends only what changed: new and cleared incidents, status level changes, filtered components degrading or recovering, and feeds that become unreadable or stale (including Azure's `lastBuildDate` check). Run it from cron or CI; nothing stays running unless you ask for it.

It can send to Telegram, to any webhook, or both.

```bash
gwen watch --dry-run                              # print what would be sent
gwen watch --interval 300                         # keep running, every 5 minutes
```

### Telegram

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts. It replies with a token like `123456789:AA...`.
2. Send your new bot any message (or add it to a group and post there), so it is allowed to message you back.
3. Find the chat id: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `"chat":{"id": ...}`. Group ids are negative, e.g. `-1001234567890`.
4. Run it:

```bash
export GWEN_TELEGRAM_TOKEN=123456789:AA...
gwen watch --telegram-chat 987654321
```

The chat id can also go in `GWEN_TELEGRAM_CHAT` or in `gwen.toml` as `[watch] telegram_chat`. The token is only read from `GWEN_TELEGRAM_TOKEN`: anyone with it controls your bot, so it never belongs in a committed file, and GWEN keeps it out of its error messages.

```cron
*/5 * * * * cd /srv/gwen && GWEN_TELEGRAM_TOKEN=123456789:AA... gwen watch
```

### Webhook

```bash
GWEN_WEBHOOK=https://example.com/hooks/gwen gwen watch
```

The webhook receives a JSON `POST` with a `text` field, which Slack, Mattermost and Rocket.Chat incoming webhooks display as-is, and an `events` list for anything that wants structure:

```json
{
  "text": "gwen: 2 changes\n- AWS: new incident: EC2: Increased error rates (us-east-1) (https://...)\n- AWS: status operational -> major",
  "events": [
    {"provider": "AWS", "kind": "incident", "summary": "new incident: ...", "url": "https://..."},
    {"provider": "AWS", "kind": "worse", "summary": "status operational -> major", "url": ""}
  ]
}
```

Event kinds: `incident`, `resolved`, `worse`, `better`, `degraded`, `recovered`, `unreadable`, `readable`.

### How it behaves

- **The first run reports anything already wrong**, so starting to watch never hides an ongoing incident. After that, an unchanged state sends nothing.
- **One failed read is not news.** A feed is reported unreadable after `unreadable_after` consecutive failures (default 2), once, and again when it recovers. In between, the last good state is kept, so a timeout never makes an incident look resolved.
- **Undelivered changes are retried.** State is saved only after every target accepts the message, so if delivery fails (exit code `3`) the next run sends the same changes again. With two targets, a failure on one means the other may get the message twice; a duplicate is better than a lost alert.
- **Keep secrets in the environment.** Prefer `GWEN_WEBHOOK` and `GWEN_TELEGRAM_TOKEN` to putting anything secret in `gwen.toml`, which is meant to be committed.
- **Keep the state file between runs.** In CI, cache or persist `.gwen-state.json`; without it every run is a first run.

Exit codes: `0` ran normally, `1` at least one feed could not be read this run, `2` bad arguments or config, `3` delivery failed.

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
