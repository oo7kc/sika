from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

from sika.market_data.mt5_backfill import (
    BackfillValidationError,
    EXPECTED_TIMEFRAMES,
    main,
    validate_backfill,
)


def next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def write_csv(path: Path, timestamps: list[int]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "time_epoch",
                "open",
                "high",
                "low",
                "close",
                "tick_volume",
                "spread_points",
                "real_volume",
            )
        )
        for index, timestamp in enumerate(timestamps):
            price = 1800 + index
            writer.writerow(
                (timestamp, price, price + 2, price - 2, price + 1, 100, 20, 0)
            )


def write_bundle(
    root: Path,
    month: str,
    *,
    timestamps: dict[str, list[int]] | None = None,
    account_overrides: dict[str, object] | None = None,
) -> Path:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    end = next_month(start)
    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())
    month_key = start.strftime("%Y%m")
    bundle_id = f"{month_key}_XAUUSDm"
    directory = root / month_key
    directory.mkdir(parents=True)

    bars: dict[str, object] = {}
    for timeframe, seconds in EXPECTED_TIMEFRAMES.items():
        values = (
            timestamps[timeframe]
            if timestamps and timeframe in timestamps
            else [start_epoch, start_epoch + seconds]
        )
        filename = f"{bundle_id}_{timeframe}.csv"
        write_csv(directory / filename, values)
        bars[timeframe] = {
            "file": filename,
            "count": len(values),
            "timeframe_seconds": seconds,
            "first_time_epoch": values[0],
            "last_time_epoch": values[-1],
            "closed_bars_only": True,
        }

    account = {
        "server": "Exness-MT5Trial9",
        "company": "Exness Technologies Ltd",
        "currency": "USD",
        "trade_mode": "demo",
        "profile": "Standard",
        "profile_source": "research-contract-v0.1",
    }
    account.update(account_overrides or {})
    manifest = {
        "schema": "sika-mt5-backfill-month-v1",
        "complete": True,
        "mode": "read-only",
        "bundle_id": bundle_id,
        "month": month,
        "requested_start_epoch": start_epoch,
        "requested_end_exclusive_epoch": end_epoch,
        "generated_at_epoch": end_epoch + 3600,
        "time_basis": {
            "bar_time": "MT5 trade-server epoch",
            "server_clock_source": "TimeTradeServer",
            "server_time_epoch": end_epoch + 3600,
            "server_minus_gmt_seconds": 0,
        },
        "terminal": {
            "name": "MetaTrader 5",
            "company": "MetaQuotes Ltd.",
            "build": 6238,
            "connected": True,
        },
        "account": account,
        "symbol": {
            "name": "XAUUSDm",
            "description": "Gold vs US Dollar",
            "digits": 3,
            "point": 0.001,
            "contract_size": 100.0,
        },
        "bars": bars,
    }
    path = directory / f"{bundle_id}_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class MT5BackfillValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_validates_every_month_and_checksums_every_file(self) -> None:
        write_bundle(self.root, "2022-01")
        write_bundle(self.root, "2022-02")

        audit = validate_backfill(
            self.root,
            start_month="2022-01",
            end_month_exclusive="2022-03",
        )

        self.assertEqual(audit.month_count, 2)
        self.assertEqual(audit.coverage["M1"].file_count, 2)
        self.assertEqual(audit.coverage["M1"].bar_count, 4)
        self.assertEqual(len(audit.bundles[0].bars["M1"].sha256), 64)
        self.assertEqual(audit.status, "review_required")

    def test_rejects_a_missing_month_in_the_requested_range(self) -> None:
        write_bundle(self.root, "2022-01")

        with self.assertRaisesRegex(BackfillValidationError, "missing monthly"):
            validate_backfill(
                self.root,
                start_month="2022-01",
                end_month_exclusive="2022-03",
            )

    def test_rejects_untrusted_account_provenance(self) -> None:
        write_bundle(
            self.root,
            "2022-01",
            account_overrides={"profile": "Raw Spread"},
        )

        with self.assertRaisesRegex(BackfillValidationError, "expected 'Standard'"):
            validate_backfill(
                self.root,
                start_month="2022-01",
                end_month_exclusive="2022-02",
            )

    def test_rejects_a_bar_outside_its_declared_month(self) -> None:
        start = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp())
        write_bundle(
            self.root,
            "2022-01",
            timestamps={"M1": [start - 60, start]},
        )

        with self.assertRaisesRegex(BackfillValidationError, "precedes"):
            validate_backfill(
                self.root,
                start_month="2022-01",
                end_month_exclusive="2022-02",
            )

    def test_intraday_missing_bar_requires_review(self) -> None:
        start = int(datetime(2022, 1, 3, 10, 0, tzinfo=UTC).timestamp())
        write_bundle(
            self.root,
            "2022-01",
            timestamps={"M1": [start, start + 60, start + 180]},
        )

        audit = validate_backfill(
            self.root,
            start_month="2022-01",
            end_month_exclusive="2022-02",
        )

        gaps = audit.coverage["M1"].review_required_gaps
        self.assertTrue(
            any(gap.interval_seconds == 120 and gap.missing_periods == 1 for gap in gaps)
        )

    def test_reports_weekend_and_rollover_closure_candidates(self) -> None:
        friday = int(datetime(2022, 1, 7, 20, 59, tzinfo=UTC).timestamp())
        sunday = int(datetime(2022, 1, 9, 22, 1, tzinfo=UTC).timestamp())
        monday = int(datetime(2022, 2, 7, 20, 59, tzinfo=UTC).timestamp())
        after_rollover = int(datetime(2022, 2, 7, 22, 1, tzinfo=UTC).timestamp())
        write_bundle(
            self.root,
            "2022-01",
            timestamps={"M1": [friday, sunday]},
        )
        write_bundle(
            self.root,
            "2022-02",
            timestamps={"M1": [monday, after_rollover]},
        )

        audit = validate_backfill(
            self.root,
            start_month="2022-01",
            end_month_exclusive="2022-03",
        )

        coverage = audit.coverage["M1"]
        self.assertGreaterEqual(coverage.weekend_closure_candidate_count, 1)
        self.assertGreaterEqual(coverage.rollover_closure_candidate_count, 1)

    def test_review_required_is_a_nonzero_cli_result_even_with_json(self) -> None:
        write_bundle(self.root, "2022-01")

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    str(self.root),
                    "--start-month",
                    "2022-01",
                    "--end-month-exclusive",
                    "2022-02",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 3)

    def test_rejects_a_companion_path_escape(self) -> None:
        manifest_path = write_bundle(self.root, "2022-01")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["bars"]["M1"]["file"] = "../outside.csv"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(BackfillValidationError, "must be"):
            validate_backfill(
                self.root,
                start_month="2022-01",
                end_month_exclusive="2022-02",
            )


if __name__ == "__main__":
    unittest.main()
