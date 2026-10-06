# Sika decision journal

This file explains how Sika is evolving in language that does not require a
software or trading background. It records the reasoning behind important
ideas and changes, what evidence supports them, and what remains uncertain.

It is not a record of private internal reasoning or a replacement for the
project's technical documents:

- `PLAN.md` says what we intend to build and in what order.
- `docs/research-contract.md` defines the research and trading rules.
- `docs/operations/mt5.md` explains how to operate the MT5 tooling.
- This journal explains why meaningful decisions were made and what they mean.

## Current direction

Sika is being rebuilt from a tool that predicted a broad daily market direction
into a selective trade-planning system for `XAUUSDm` on an Exness Standard demo
account. A future call should say whether the idea is long or short, where an
entry remains valid, where the stop-loss and take-profit are, the risk/reward,
when the idea expires, and how reliable the model believes the exact setup is.

The system is currently read-only. It collects and validates market data but
cannot place, modify, or close a trade. Telegram delivery and any use with real
money come only after offline research and paper-trading evidence pass the gates
in the project plan.

## Decisions currently in force

- Start with `XAUUSDm`, not `XAUUSD247` or several markets at once.
- Use completed M15 candles for possible entries and H1 candles for broader
  market context.
- Observe the full 08:00–16:00 New York session, allow new candidates only from
  08:15 through 14:00, and use the final two hours for monitoring existing ideas.
- Use the Exness MT5 feed intended for execution so research prices and eventual
  discretionary trading prices are comparable.
- Keep execution manual. Confidence may filter weak ideas, but it must not be
  used to justify larger leverage.
- Treat “no trade” as a valid and expected result.
- Fail closed when data, account identity, timing, or file integrity is doubtful.

## Current state

- The research contract and staged plan are written but still require review.
- MT5 works through Wine and is connected to the Exness Standard demo account.
- Read-only MQL5 exporters and an independent Python validator are implemented.
- A fresh schema-version-2 M15/H1 sample export passed the validator. This
  confirms that the terminal-to-file-to-validator path works end to end.
- A resumable five-year M1/M15/H1 exporter and independent whole-range validator
  are implemented and installed. October and November 2021 have been exported;
  the remaining months can resume without replacing them.
- Historical data exists near the October 2021 five-year boundary for M1, M15,
  and H1. This proves availability at that point, not uninterrupted coverage.
- The next milestone is to run the backfill and reconcile any gaps with broker
  holiday or maintenance schedules. Model research has not started.

## Change journal

### 2026-10-06 — Corrected a false manifest-write failure

**What happened:** The first backfill runs wrote valid October and November 2021
CSV files and manifests, but then reported that each manifest write had failed.
The script compared the number of bytes written by MT5 with the number of text
characters in the manifest. Windows-style newline conversion makes those counts
different even when the file is written successfully.

**What changed:** All three read-only MT5 scripts now treat a nonzero write with
no MT5 error as success. The corrected sources and binaries are installed, and a
focused regression test protects this rule.

**Evidence:** Each script compiles with zero errors and zero warnings. The
installed source and binary hashes match the reviewed builds. All 26 repository
tests pass, and the independent validator accepted both existing monthly bundles
as structurally sound while correctly reserving their market-closure gaps for
later review.

**Next:** Refresh MT5's Scripts list and rerun `SikaExportHistory` with the same
defaults. It will skip October and November 2021 and resume at December 2021.

### 2026-10-06 — Implemented the resumable five-year backfill

**What changed:** Added an MT5 script that exports 60 complete calendar months
of M1, M15, and H1 data in restart-safe monthly bundles. Added an independent
validator that verifies every expected month, file identity, account source,
timestamp, price, checksum, overlap, and gap across the whole range.

**Why:** A single multi-year file would be difficult to restart, inspect, or
repair. Monthly completion markers allow an interrupted run to continue without
re-exporting good months, and make any bad month replaceable in isolation.

**Status and evidence:** Implemented and installed, but not yet exercised on the
full real dataset. Twenty-five Python tests pass. The MQL5 exporter compiles
with zero errors and zero warnings, and its installed binary matches the source
that was compiled.

**Important limit:** Weekend and normal daily gold closures can be recognized
as candidates from their timing. Holiday and maintenance gaps cannot be assumed
valid without matching them to an independent historical schedule, so the
validator reports them for review and refuses to call the dataset ready.

**Next:** Run `SikaExportHistory`, validate all 60 months, and investigate every
gap marked `review_required` before feature or model work begins.

### 2026-10-06 — Validated the complete sample-export path

**What changed:** A fresh export from the updated MT5 script returned `VALID`
when checked by the independent Python validator.

**Why:** Finding old history was only one part of the data problem. Before
building a multi-year downloader, we also needed proof that MT5 can produce the
agreed files and that a separate program can verify their identity, timing,
shape, completeness, and price integrity.

**Status:** The small-sample data path is implemented and validated. This clears
the gate for building the larger historical backfill; it does not yet validate
five years of continuous data.

**Next:** Build the resumable M1/M15/H1 backfill and its continuity report.

### 2026-10-06 — Established this decision journal

**What changed:** Added this document and a repository rule requiring it to be
updated alongside meaningful implementation, research, product, or operating
changes.

**Why:** The plan and research contract are necessarily detailed. We also need a
single place where a non-technical reader can understand why the project is
changing and whether an idea is merely proposed, approved, or already built.

**What it means:** Future changes are incomplete until their plain-language
rationale, effect, evidence, and next step are recorded here. Small formatting
or typo-only edits do not need their own entry.

### 2026-10-06 — Hardened the read-only MT5 data boundary

**What changed:** The exporter and validator now accept only the agreed
`XAUUSDm` Exness demo context and reject incomplete history, malformed prices,
unexpected file columns, suspicious time differences, future-dated quotes, and
incorrect account metadata. A safety test prevents the MQL5 scripts from gaining
trade execution or sensitive-account capabilities unnoticed.

**Why:** A model can appear successful when its input data are incomplete,
mis-timed, or taken from a different account or instrument. It is safer to stop
than to quietly continue with data that no longer represent the experiment.

**Evidence:** Seventeen focused tests pass, both MQL5 scripts compile with zero
errors and zero warnings, and the installed scripts match the reviewed sources.

**Next:** Produce a fresh schema-version-2 export before using sample data in the
backfill work.

### 2026-10-06 — Confirmed older Exness history is reachable

**What changed:** A bounded MT5 probe found M1, M15, and H1 data around
1 October 2021. The server reports history beginning in June 2018.

**Why:** The research plan calls for roughly five years of market history. Before
building a large downloader, we needed to know whether the chosen broker could
supply data near that boundary.

**What it means:** A five-year study appears feasible, but a proper backfill must
still prove that the interval is continuous and identify genuine market closures
versus missing data.

### 2026-10-04 — Chose executable trade plans over daily direction

**Idea:** Replace the old “market up or down today” output with a precise trade
candidate containing an entry, stop-loss, take-profit, expiry, risk/reward, and
calibrated probability.

**Why:** A daily direction can be correct yet still be impossible to trade
profitably. A trade plan can be tested against actual bid/ask prices, transaction
costs, timing, and risk.

**Status:** Approved as the product direction. Exact thresholds remain draft
until the research contract is reviewed and frozen.

## How to add the next entry

Add the newest entry at the top of the change journal and explain:

1. What changed or what idea is being considered.
2. Why it matters, without relying on technical shorthand.
3. Whether it is proposed, approved, implemented, tested, or rejected.
4. What evidence or validation exists.
5. What should happen next or what remains uncertain.

Never include passwords, account numbers, Telegram tokens, personal data, or
other secrets in this journal.
