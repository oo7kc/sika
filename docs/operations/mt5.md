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
