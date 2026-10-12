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
gwen regions azure                # region names usable in targets, e.g. azure/scus
gwen watch                        # send changes to Telegram or a webhook (see Alerts)
gwen investigate azure/scus       # what else happened around a target's last problem
gwen setup telegram               # connect a Telegram bot: token, chat id, test message
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
work_hours = "Mon-Fri 08:00-18:00"
timezone = "America/Chicago"   # default: this computer's time zone

[[watch.rule]]                 # how loudly to announce changes; see Priorities
target = "azure/scus"
priority = 1
failover = ["azure/ncus"]

[[watch.rule]]
target = "azure/ncus"
priority = 2
```

Every command respects `providers` and the extra Statuspage vendors. Filters and rules only apply to `gwen watch`; `gwen status` still shows each provider's whole picture. Filters decide what is tracked at all; rules decide how loudly a tracked change is announced, and are usually what you want.

## Alerts: `gwen watch`

`gwen watch` compares the current state with the previous run and sends only what changed: new and cleared incidents, status level changes, filtered components degrading or recovering, and feeds that become unreadable or stale (including Azure's `lastBuildDate` check). Run it from cron or CI; nothing stays running unless you ask for it.

It can send to Telegram, to any webhook, or both.

```bash
gwen watch --dry-run                              # print what would be sent
gwen watch --interval 300                         # keep running, every 5 minutes
```

### Telegram

```bash
gwen setup telegram
```

It walks you through it:

1. If you don't have a bot yet, it tells you how to make one: message [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name. Telegram only gives bot tokens to people, so this is the one step GWEN can't do for you.
2. You paste the token. It isn't shown on screen, and GWEN checks it with Telegram straight away.
3. You open the bot's chat and press **Start**. GWEN waits for that message and takes the chat id from it. If several chats have messaged the bot, it asks which one.
4. It sends a test message to that chat, then saves the token and chat id as `GWEN_TELEGRAM_TOKEN` and `GWEN_TELEGRAM_CHAT`. On Windows they are saved as user environment variables, so scheduled tasks pick them up. Elsewhere it prints the two lines to add to your crontab or service environment.

Run it again with `--new-token` to switch bots. If the bot already has a webhook set by another tool, setup stops instead of removing it.

**Doing it by hand** (CI, servers): set `GWEN_TELEGRAM_TOKEN` to the token, send the bot a message, open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}` (group ids are negative), then:

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

Each event also carries `priority`, the `targets` it matched and the provider `key`. Changes released after being held for work hours arrive in a separate `held` list, each with the time it was first `seen`, and under "While you were away" in `text`.

Event kinds: `incident`, `resolved`, `worse`, `better`, `degraded`, `recovered`, `unreadable`, `readable`, `failover`, `failover-end`.

### Priorities: what reaches you, and when

Without any `[[watch.rule]]`, every change is sent straight away. Rules let you say which services and regions matter, and how much:

| Priority | What happens |
|----------|--------------|
| `1` | Sent immediately, at any hour. |
| `2` | Sent during `work_hours`. Outside them it is held, and everything held is sent together, under **While you were away**, on the first run after work hours start. Nothing is dropped. |
| `3` | Not sent. Recorded in the history only. This is the default for anything no rule covers; change it with `[watch] default_priority`. |

```toml
[watch]
work_hours = "Mon-Fri 08:00-18:00"   # also "Mon,Wed,Fri 09:00-17:00"; same-day hours only
timezone = "America/Chicago"         # IANA name; default: this computer's time zone
default_priority = 3

[[watch.rule]]
target = "azure/scus"      # a region of a provider...
priority = 1
failover = ["azure/ncus"]  # ...and where its load goes if it fails

[[watch.rule]]
target = "azure/ncus"
priority = 2

[[watch.rule]]
target = "cloudflare/dfw"  # Cloudflare locations by airport code
priority = 1

[[watch.rule]]
target = "github"          # a whole provider
priority = 2
```

**Targets.** A target is a provider (`github`) or `provider/region`. Azure, AWS and GCP regions are checked against a built-in list, so short and long names both work: `azure/scus`, `azure/southcentralus` and `azure/South Central US` are the same target, as are `aws/us-east-1` and `gcp/us-central1`. For other providers the region is matched as a whole word in incident and component names, so `cloudflare/dfw` matches "Dallas, TX, United States - (DFW)". A rule on a region of a Statuspage provider also turns on alerts for that region's components.

**Matching.** AWS and GCP state which regions an incident affects; Azure's public feed only says so in the title, so GWEN reads region names from it, taking care that "Central US" is not mistaken for "South Central US". An Azure, AWS or GCP incident that names **no** region is treated as affecting **every** region of that provider: an extra alert is better than a missed one. A change gets the most urgent priority of every rule it matches; a provider's feed becoming unreadable gets the most urgent priority of any rule on that provider, because it hides all of them; a status level change follows the change that caused it.

**Failover.** While a priority-1 target has an ongoing incident or degraded component, the targets in its `failover` list are treated as priority 1 too, since that is where the load goes. GWEN says so when it starts ("azure/northcentralus is now priority 1 while azure/southcentralus has problems") and when it ends. `failover` is only allowed on priority-1 rules.

**History.** Every change, at every priority, is recorded in `.gwen-history.sqlite` next to the state file (or `[watch] history = "path"`), with how it was routed: `notify`, `hold` or `log`. It is plain SQLite, so any SQLite tool can read it.

`gwen regions azure` lists every region name GWEN recognises for a provider, with Azure's paired regions, which are the natural `failover` targets.

### Investigating: `gwen investigate`

When a target has a problem, `gwen investigate` lays out everything the history recorded around it, including priority-3 changes nobody was alerted about:

```bash
gwen investigate azure/scus                          # around its most recent problem
gwen investigate azure/scus --at "2026-10-11 14:00"  # around a time (local, or ISO 8601)
gwen investigate aws/us-east-1 --window 6h           # default window: 2h either side
```

```
azure/southcentralus around Mon 2026-10-12 10:00 (±2h): 6 recorded changes
 When       │       │ P │ Provider   │ Change                                  │ Related as
 Mon 08:30  │ -1h30m│ 3 │ GCP        │ new incident: Networking in us-south1   │ area
 Mon 09:30  │ -30m  │ 2 │ Azure      │ new incident: Latency in North Central… │ failover
 Mon 09:50  │ -10m  │ 3 │ Cloudflare │ degraded: Dallas, TX - (DFW)            │ area
 Mon 10:00  │ +0m   │ 1 │ Azure      │ new incident: Outage in South Central US│ target
 Mon 10:20  │ +20m  │ 3 │ Azure      │ new incident: Storage in West Europe    │ provider
 Mon 10:45  │ +45m  │ 3 │ AWS        │ new incident: Errors (Tokyo)            │ other
2 related changes were priority 3 and not sent at the time.
```

Each change is related to the target as `target` (the target itself), `failover` (a region in its rule's `failover` list), `provider` (another region of the same provider), `area` (another provider in the same part of the world) or `other`. It only sees what `gwen watch` recorded, so it needs `watch` running on a schedule beforehand.

### How it behaves

- **The first run reports anything already wrong**, so starting to watch never hides an ongoing incident. After that, an unchanged state sends nothing.
- **One failed read is not news.** A feed is reported unreadable after `unreadable_after` consecutive failures (default 2), once, and again when it recovers. In between, the last good state is kept, so a timeout never makes an incident look resolved.
- **Undelivered changes are retried.** State and history are saved only after every target accepts the message, so if delivery fails (exit code `3`) the next run sends the same changes again. With two targets, a failure on one means the other may get the message twice; a duplicate is better than a lost alert.
- **`--dry-run` prints instead of sending.** It still advances the state and records history, so the next real run does not repeat what the dry run showed, but changes held for work hours stay held.
- **Keep secrets in the environment.** Prefer `GWEN_WEBHOOK` and `GWEN_TELEGRAM_TOKEN` to putting anything secret in `gwen.toml`, which is meant to be committed.
- **Keep the state and history files between runs.** In CI, cache or persist `.gwen-state.json` and `.gwen-history.sqlite`; without the state every run is a first run, and without the history held changes are lost.

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
├── config.py       # gwen.toml
├── providers.py    # one fetcher per vendor, normalised to a common shape
├── regions.py      # geographic grouping for components and maintenance
├── targets.py      # provider/region targets and the Azure, AWS and GCP region lists
├── policy.py       # priority rules and work hours
├── watch.py        # change detection, routing and delivery for `gwen watch`
├── history.py      # the SQLite history of every change
├── investigate.py  # relating recorded changes around a problem
└── telegram_setup.py  # `gwen setup telegram`
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
