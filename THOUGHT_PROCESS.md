# Sika decision journal

This file explains how Sika is evolving. It records the reasoning behind important
ideas and changes, what evidence supports them, and what remains uncertain.

## Current direction

Sika is being rebuilt from a tool that predicted a broad daily market direction
into a selective trade-planning system for `XAUUSDm` on an Exness Standard demo
account. A future call should say whether the idea is long or short, where an
entry remains valid, where the stop-loss and take-profit are, the risk/reward,
when the idea expires, and how reliable the model believes the exact setup is.

The system is currently read-only. It collects and validates market data but
cannot place, modify, or close a trade. Telegram delivery and any use with real
money come only after offline research and paper-trading evidence pass the gates
in the research contract.

## Decisions currently in force

- Starting with `XAUUSDm`.
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

- The research contract is written but still requires review as implementation
  reaches each promotion gate.
- MT5 works through Wine and is connected to the Exness Standard demo account.
- Read-only MQL5 exporters and an independent Python validator are implemented.
- A fresh schema-version-2 M15/H1 sample export passed the validator. This
  confirms that the terminal-to-file-to-validator path works end to end.
- The full 60-month M1/M15/H1 history from October 2021 through September 2026
  has been exported. Every monthly bundle passed the structural and identity
  checks, but the dataset remains under review until its unexplained gaps are
  reconciled.
- A versioned closure calendar and gap-reconciliation audit are implemented.
  They identify 76 New York sessions that downstream research must exclude,
  including 24 sessions quarantined because of unexplained feed gaps.
- Historical data exists near the October 2021 five-year boundary for M1, M15,
  and H1. This proves availability at that point, not uninterrupted coverage.
- The next milestone is to enforce the reconciled session exclusions in the
  canonical research dataset. Model research has not started.

## Change journal

### 2026-10-06 — Prepared the active project for collaboration

**What changed:** Separated the old daily-direction prototype from the active
`XAUUSDm` system, removed it from active packaging and dependencies, replaced
the product README, and added contributor and architecture guidance. Operational
logging now has validated settings and can write bounded, rotating JSON-line
logs without copying arbitrary fields that might contain secrets.

**Why:** A new contributor should see one product direction and one supported
workflow. Historical code is still recoverable, but it must not appear to be an
approved model or silently influence the current environment. Research settings
also need to remain reviewable instead of being hidden in a private `.env` file.

**What it means:** The repository root now represents only the system we are
building. The frozen prototype remains under `archive/daily_direction_v0`, and
local prototype data, models, logs, and credentials remain ignored. Versioned
research configuration and operational logging have separate responsibilities.

**Evidence:** A clean locked environment installs with only the active package;
the legacy scientific stack is no longer installed. Thirty-eight focused tests
and the repository static checks pass. The publishable-file inventory confirms
that archived credentials, generated models, data, logs, caches, and compiled
MQL5 files remain excluded.

**Next:** Implement the canonical dataset builder that enforces all reconciled
session exclusions.

### 2026-10-06 — Reconciled holidays and quarantined unexplained gaps

**What changed:** Added a versioned `XAUUSDm` closure calendar with named
official sources and an independent reconciliation tool. It matches observed
gaps to recognized metal-market holidays, detects whether unexplained gaps touch
the New York operating window, and produces an explicit list of sessions that
future research must exclude.

**Evidence:** Of the original review gaps, 57 M1, 49 M15, and 32 H1 gaps align
with calendar dates. The tool leaves 109 M1, 12 M15, and 5 H1 gaps quarantined
rather than pretending their cause is known. These resolve to 24 quarantine
session dates and 76 total excluded dates after holiday and early-close sessions
are included. Thirty-four focused repository tests pass.

**What it means:** The gap inventory is now reproducible and actionable, but the
dataset still fails closed. Calendar correlation supports excluding an abnormal
session; it does not prove the broker's exact historical schedule. Unmatched
gaps remain recorded as feed gaps, and no missing bar is fabricated.

**Next:** The canonical dataset builder must consume every excluded date and a
test must prove that it cannot emit a research candidate from those sessions.
Only then can this data-quality gate be considered passed.

### 2026-10-06 — Completed the five-year history export

**What changed:** The resumable exporter produced all 60 monthly bundles from
October 2021 through September 2026. The independent validator checked every
manifest and M1, M15, and H1 file across the complete range.

**Evidence:** The audit accepted 1,765,731 M1 bars, 118,063 M15 bars, and 29,548
H1 bars. All file identities, account metadata, monthly boundaries, price rows,
ordering, and checksums passed. The audit result is `REVIEW_REQUIRED`, with 166
M1, 61 M15, and 37 H1 gaps still requiring explanation.

**What it means:** The export mechanism and monthly dataset are structurally
sound. This is not yet permission to train a model: many gaps resemble known
holiday closures, while smaller isolated gaps may be broker-feed or market-data
interruptions and must be classified explicitly rather than silently filled.

**Next:** Match the gaps against historical gold trading hours and holidays,
record which closures are expected, and decide how genuine feed gaps will be
represented during research.

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
