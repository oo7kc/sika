# Architecture

## Purpose

Sika is designed as a selective trade-planning system rather than a daily price
direction predictor. The architecture keeps data provenance, research,
decision-making, delivery, and any future execution separate so that each stage
can be reviewed and stopped independently.

## Current flow

```text
Exness MT5 demo feed
        |
read-only MQL5 monthly exports
        |
independent Python validation and checksums
        |
holiday correlation and feed-gap quarantine
        |
canonical research dataset (next milestone)
```

Only the first four stages exist. The validation boundary deliberately returns
nonzero statuses when human review or downstream quarantine is still required.
That is a safety state, not a command failure to work around.

## Active components

- `mt5/Scripts/` contains read-only terminal scripts. A regression test rejects
  order APIs and sensitive account fields.
- `src/sika/market_data/` validates exported bars, complete monthly backfills,
  MT5 environment probes, and historical gap classifications.
- `config/market_data/` contains reviewable inputs that can alter data
  eligibility. Each file is versioned and referenced by generated receipts.
- `src/sika/configuration.py` validates operational settings. It intentionally
  cannot change research rules.
- `src/sika/logging_config.py` provides consistent console and optional rotating
  JSON-line logs without serializing arbitrary fields.
- `tests/` protects account/data identity, closed-bar rules, path safety, price
  geometry, continuity, gap quarantine, log privacy, and the no-trading boundary.

## Planned boundaries

Future stages should be separate modules with explicit inputs and immutable
outputs:

1. Canonical dataset construction enforces session exclusions and aligns M1,
   M15, and H1 without look-ahead.
2. Feature and label construction records all parameters and data hashes.
3. Walk-forward evaluation includes spread, slippage, and `NO_TRADE` outcomes.
4. Probability calibration produces confidence only for the exact trade plan.
5. Signal construction emits a versioned plan containing entry, SL, TP, R:R,
   expiry, confidence, and provenance.
6. Telegram delivery renders an already-approved plan; it does not invent or
   modify trading decisions.
7. Any future execution adapter is a distinct, opt-in component with independent
   risk controls and review. It is not part of the current system.

## Reproducibility rules

- Python is pinned to 3.12.9 and dependencies are resolved by `uv.lock`.
- Research inputs are committed; generated data and reports are not.
- Export manifests and validation receipts include time ranges, broker context,
  schema versions, and file checksums.
- Time calculations use explicit UTC or IANA time zones. New York session logic
  must use `America/New_York`, not a fixed offset.
- A dataset, experiment, or trade plan must identify the input/configuration
  versions that produced it.
- Missing or ambiguous information is excluded or quarantined, never silently
  repaired.

## Archived predecessor

The old daily-direction prototype is preserved in `archive/daily_direction_v0`
for historical context only. It is outside active packaging and testing because
its target, data source, validation claims, and model artifacts do not satisfy
the current research contract.
