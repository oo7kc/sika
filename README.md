# Sika

Sika is an in-progress, research-validated trade-planning system for `XAUUSDm`
on an Exness Standard account. Its intended output is a discretionary trade
plan: direction, entry, stop-loss, take-profit, risk/reward, expiry, and a
calibrated confidence estimate. Telegram delivery is planned after the research
and paper-trading gates pass.

Sika is currently a **read-only market-data system**. It cannot place, modify,
or close trades, and it does not yet produce a trade call. Treat every current
command as data collection or validation tooling, not trading advice.

## Current status

The MT5-to-research data boundary is working end to end:

- the terminal is restricted to the agreed `XAUUSDm` Exness demo context;
- MQL5 scripts export completed M1, M15, and H1 bars without order access;
- Python validators check identity, ranges, ordering, prices, and checksums;
- the five-year backfill covers October 2021 through September 2026; and
- gap reconciliation produces explicit session exclusions instead of filling
  or ignoring missing data.

The dataset remains fail-closed. The next milestone is a canonical dataset
builder that proves excluded sessions cannot enter research. Model development,
confidence calibration, Telegram delivery, and trade execution have not begun.

The authoritative project documents are:

- [Decision journal](THOUGHT_PROCESS.md) — plain-language decisions, evidence,
  current state, and next steps.
- [Research contract](docs/research-contract.md) — strategy, risk, evaluation,
  and promotion rules.
- [Architecture](docs/architecture.md) — system boundaries and reproducibility
  decisions.
- [MT5 operations](docs/operations/mt5.md) — Wine/MT5 setup, export, validation,
  and failure recovery.
- [Contributing](CONTRIBUTING.md) — the local quality workflow and review rules.

## Product contract

When implemented, a trade call must contain all of the following or resolve to
`NO_TRADE`:

- exact instrument and long/short direction;
- a bounded entry rule rather than an untradeable daily prediction;
- stop-loss, take-profit, and explicit risk/reward;
- a session-aware expiry;
- calibrated confidence for that exact setup; and
- the assumptions needed to reproduce the call.

The initial operating window is 08:00–16:00 New York time. New M15 candidates
may be created from 08:15 through 14:00, using H1 context; the final two hours
are for monitoring existing plans. Execution remains manual until a separate,
explicitly reviewed execution phase is approved.

## Repository layout

```text
config/                 versioned research inputs and closure calendars
docs/                   architecture, research, and operating documentation
mt5/Scripts/            read-only MQL5 exporters and probes
src/sika/               active Python package
tests/                  safety and data-contract regression tests
archive/                frozen predecessor source; excluded from active tooling
data/, logs/, models/    ignored local outputs, with tracked placeholders only
```

The predecessor daily-direction prototype is frozen under
[`archive/daily_direction_v0`](archive/daily_direction_v0/README.md). It is not
part of the active package, dependency lock, test suite, or product claims.

## Development setup

Prerequisites:

- Python 3.12.9
- [uv](https://docs.astral.sh/uv/)
- MT5 only for terminal-facing workflows

Create the locked Linux development environment:

```bash
uv sync --locked
```

On native 64-bit Windows, install the optional MetaTrader5 bridge as well:

```powershell
uv sync --locked --extra windows-mt5
```

Run the focused regression suite and static checks:

```bash
uv run python -m unittest discover -s tests -v
uvx --from ruff==0.15.20 ruff check .
```

The MQL5 sources must additionally compile in the supported MetaEditor build
with zero errors and zero warnings. Compiled `.ex5` files are local build
artifacts and are not committed.

## Data workflow

The detailed operator procedure is in [the MT5 runbook](docs/operations/mt5.md).
The primary validation commands are:

```bash
uv run sika-mt5-validate-export path/to/export_manifest.json

uv run sika-mt5-validate-backfill path/to/backfill \
  --output data/xauusdm-backfill-audit.json

uv run sika-mt5-reconcile-gaps path/to/backfill \
  --calendar config/market_data/xauusdm-closures-v1.json \
  --output data/xauusdm-gap-reconciliation.json
```

Important nonzero statuses are deliberate safety outcomes:

- exit `3`: structurally valid backfill still has gaps requiring review;
- exit `4`: reconciliation succeeded, but downstream research must enforce the
  reported quarantine and exclusion dates.

Never synthesize bars or add a closure date merely to make these commands pass.

## Configuration and logs

Research assumptions live in reviewed, version-controlled files under
`config/`. Operational logging is the only environment-configured behavior:

```bash
export SIKA_LOG_LEVEL=INFO
export SIKA_LOG_FORMAT=json
export SIKA_LOG_FILE=logs/sika.jsonl
```

Supported levels are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`;
supported formats are `text` and `json`. Logs rotate at 5 MiB with five backups.
JSON output contains a timestamp, level, logger, message, and approved event
name. Arbitrary record fields are not serialized, which reduces accidental
credential leakage.

Local data, reports, logs, compiled MQL5 binaries, models, virtual environments,
and `.env` files are ignored. Commit schemas, calendars, source, and tests—not
broker credentials, account numbers, Telegram tokens, or generated datasets.

## Safety notice

Trading leveraged products can result in substantial loss. Passing software
tests proves only that the code follows its declared contracts; it does not
prove profitability or suitability for live trading.
