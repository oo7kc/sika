# MT5 data operations

This runbook covers the read-only boundary between Sika and the confirmed Exness
Standard demo account. It explains how to run and diagnose the tooling; the data
rules themselves live in [`../research-contract.md`](../research-contract.md).

## Safety boundary

The current MT5 integration can select `XAUUSDm`, read terminal/account metadata,
read quotes and history, and write files inside MT5's sandbox. It cannot submit,
modify, or close orders. It does not accept or persist account credentials.

Account subtype is not exposed by the MT5 APIs used here. Export metadata records
`Standard` as a research-contract assertion, while server, company, demo mode,
symbol specification, quotes, and bars are obtained from MT5 and validated.

Keep **Algo Trading** disabled during this stage.

## Linux/Wine workflow

The native MQL5 route is the supported workflow on Linux. The versioned sources
are in [`../../mt5/Scripts`](../../mt5/Scripts).

Use **File → Open Data Folder** in MT5 to locate the authoritative data folder.
For the current portable Wine installation it is:

```text
~/.mt5/drive_c/Program Files/MetaTrader 5
```

Install both `.mq5` sources and their MetaEditor-compiled `.ex5` artifacts under
`MQL5/Scripts/Sika/`. In Navigator (`Ctrl+N`), right-click **Scripts**, select
**Refresh**, and expand **Scripts → Sika**.

### Closed-bar sample

Run `SikaExportBars` on an `XAUUSDm` chart with its defaults. It exports exact,
closed M15 and H1 samples to `MQL5/Files/Sika/exports/` and writes the manifest
last. A dataset without its matching manifest is incomplete and must not be used.

Validate a completed export from Linux:

```bash
uv run sika-mt5-validate-export \
  "$HOME/.mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/Sika/exports/<export-id>_XAUUSDm_manifest.json"
```

Use `--json` when a machine-readable receipt with ranges, gap counts, and SHA-256
checksums is required. Invalid data produces a nonzero exit code.

### Historical availability

Set **Tools → Options → Charts → Max bars in chart** high enough for the intended
history and restart MT5. The current environment uses `100000000` (“Unlimited”).

Run `SikaHistoryProbe` once with its defaults. It requests only a bounded week
around 1 October 2021 for M1, M15, and H1, then writes its redacted result to
`MQL5/Files/Sika/probes/`. This establishes availability near the five-year
boundary; it is not the historical backfill and does not prove full continuity.

### Five-year historical backfill

Run `SikaExportHistory` with its defaults to export the fixed v0 interval:

```text
2021-10-01 00:00 UTC <= bar open time < 2026-10-01 00:00 UTC
```

The script creates 60 monthly directories under `MQL5/Files/Sika/backfill/`.
Each contains M1, M15, and H1 CSV files plus a manifest. The manifest is written
last, so its presence is the completion marker for that month. Completed months
are skipped on a later run; an interrupted month is rebuilt automatically.

Keep `InpOverwriteCompleted` set to `false` during normal operation. Set it to
`true` only when replacing a month that the independent validator rejected. In
that mode the script removes the old completion marker before touching its CSV
files, so a failed replacement cannot appear complete.

The script reports each completed or skipped month in **Toolbox → Experts** and
finishes with:

```text
Sika history backfill complete: months=60, exported=..., skipped=....
```

Validate the full range and write a durable receipt from Linux:

```bash
uv run sika-mt5-validate-backfill \
  "$HOME/.mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/Sika/backfill" \
  --output data/xauusdm-backfill-audit.json
```

`STRUCTURALLY_VALID` means all 60 monthly bundles, identities, ranges, file
shapes, prices, ordering, and checksums passed with no unexplained gaps.
`REVIEW_REQUIRED` means the files are structurally sound but one or more gaps
must still be reconciled with historical holiday or maintenance schedules. It
returns exit code 3 and must not be treated as research-ready. Weekend and the
usual 21:00/22:00 UTC rollover closures are reported separately as closure
candidates rather than silently discarded. [Exness documents](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours)
that its servers use UTC+0 and that gold is usually closed during rollover;
historical holidays still require explicit reconciliation.

The date-range exporter uses bar-open timestamps. MQL5
[`CopyRates`](https://www.mql5.com/en/docs/series/copyrates) treats both
date-range boundaries as inclusive, so the script requests the final second
before the next month to implement a clean half-open monthly interval.

## Native Windows fallback

On 64-bit Windows, the optional `sika-mt5-probe` command can attach to a signed-in
terminal through MetaQuotes' Python package:

```powershell
uv sync
uv run sika-mt5-probe --symbol XAUUSDm --bars 500 `
  --output data/probes/xauusdm.json
```

Pass `--terminal-path` only when terminal discovery fails. The command is not the
Linux/Wine bridge; MetaQuotes does not publish a Linux wheel for that package.

## Failure handling

The tools fail closed on a wrong symbol, non-Exness server/company, non-demo
account, disconnected terminal, incomplete history request, malformed OHLC,
non-monotonic timestamps, a material server/GMT offset, altered CSV shape, or a
missing completion file. Do not weaken a check to make an export pass. Correct
the terminal state, allow history synchronization to finish, and rerun.

An Experts message that reports a write failure with `error=0` indicates a
script defect rather than an operating-system write error. Do not delete the
monthly files or enable overwrite. Preserve the output, install the corrected
script, and rerun normally so completed monthly manifests are skipped.

Use the MT5 **Experts** or **Journal** tab for MQL5 messages. If those tabs are not
visible, press `Ctrl+T` to open Toolbox. On Linux, the output directories can also
be inspected directly without relying on the terminal UI.

## Verification for contributors

Run the Python contract and safety tests with:

```bash
python -m unittest discover -s tests -v
```

Every changed `.mq5` source must also compile in the supported MetaEditor build
with zero errors and zero warnings before its `.ex5` is installed. Compiled files
are build artifacts and are intentionally excluded from Git.
