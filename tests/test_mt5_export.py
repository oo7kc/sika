from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from sika.market_data.mt5_export import ExportValidationError, validate_export


EXPORT_ID = "20261006T073318Z"
# Exact UTC hour boundary so both H1 and M15 fixture bars are aligned.
GENERATED_AT = 1_800_000_000


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
            price = 4100 + index
            writer.writerow((timestamp, price, price + 2, price - 2, price + 1, 10, 20, 0))


def bar_manifest(filename: str, timestamps: list[int], seconds: int) -> dict[str, object]:
    return {
        "file": filename,
        "count": len(timestamps),
        "timeframe_seconds": seconds,
        "first_time_epoch": timestamps[0],
        "last_time_epoch": timestamps[-1],
        "forming_bar_excluded": True,
    }


class MT5ExportValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.m15_times = [GENERATED_AT - 3600, GENERATED_AT - 2700]
        self.h1_times = [GENERATED_AT - 10800, GENERATED_AT - 7200]
        self.m15_name = f"{EXPORT_ID}_XAUUSDm_M15.csv"
        self.h1_name = f"{EXPORT_ID}_XAUUSDm_H1.csv"
        write_csv(self.root / self.m15_name, self.m15_times)
        write_csv(self.root / self.h1_name, self.h1_times)
        self.manifest = {
            "schema_version": 2,
            "complete": True,
            "mode": "read-only",
            "export_id": EXPORT_ID,
            "generated_at_epoch": GENERATED_AT,
            "time_basis": {
                "bar_time": "MT5 server epoch",
                "server_time_epoch": GENERATED_AT,
                "server_minus_gmt_seconds": 0,
            },
            "terminal": {
                "name": "MetaTrader 5",
                "company": "MetaQuotes Ltd.",
                "build": 6238,
                "connected": True,
            },
            "account": {
                "server": "Exness-MT5Trial9",
                "company": "Exness Technologies Ltd",
                "currency": "USD",
                "trade_mode": "demo",
                "profile": "Standard",
                "profile_source": "research-contract-v0.1",
            },
            "symbol": {
                "name": "XAUUSDm",
                "description": "Gold vs US Dollar",
                "digits": 3,
                "point": 0.001,
                "contract_size": 100.0,
                "volume_min": 0.01,
                "volume_step": 0.01,
                "volume_max": 200.0,
            },
            "latest_tick": {
                "time_msc": GENERATED_AT * 1000 - 1000,
                "bid": 4139.0,
                "ask": 4139.2,
            },
            "bars": {
                "M15": bar_manifest(self.m15_name, self.m15_times, 900),
                "H1": bar_manifest(self.h1_name, self.h1_times, 3600),
            },
        }
        self.manifest_path = self.root / f"{EXPORT_ID}_XAUUSDm_manifest.json"
        self.write_manifest()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_valid_export_returns_a_checksummed_audit(self) -> None:
        audit = validate_export(self.manifest_path)

        self.assertEqual(audit.symbol, "XAUUSDm")
        self.assertEqual(audit.bars["M15"].count, 2)
        self.assertEqual(len(audit.bars["M15"].sha256), 64)
        self.assertEqual(audit.warnings, ())

    def test_rejects_a_manifest_that_can_escape_its_directory(self) -> None:
        self.manifest["bars"]["M15"]["file"] = "../outside.csv"
        self.write_manifest()

        with self.assertRaisesRegex(ExportValidationError, "must be"):
            validate_export(self.manifest_path)

    def test_rejects_a_duplicate_timestamp(self) -> None:
        write_csv(self.root / self.m15_name, [self.m15_times[0], self.m15_times[0]])
        self.manifest["bars"]["M15"]["last_time_epoch"] = self.m15_times[0]
        self.write_manifest()

        with self.assertRaisesRegex(ExportValidationError, "strictly increasing"):
            validate_export(self.manifest_path)

    def test_rejects_a_bar_that_was_still_forming(self) -> None:
        forming_time = GENERATED_AT - 900
        write_csv(self.root / self.m15_name, [GENERATED_AT - 1800, forming_time])
        self.manifest["bars"]["M15"]["first_time_epoch"] = GENERATED_AT - 1800
        self.manifest["bars"]["M15"]["last_time_epoch"] = forming_time
        self.write_manifest()

        audit = validate_export(self.manifest_path)
        self.assertEqual(audit.bars["M15"].last_time_epoch, forming_time)

        too_new = GENERATED_AT
        write_csv(self.root / self.m15_name, [GENERATED_AT - 900, too_new])
        self.manifest["bars"]["M15"]["first_time_epoch"] = GENERATED_AT - 900
        self.manifest["bars"]["M15"]["last_time_epoch"] = too_new
        self.write_manifest()
        with self.assertRaisesRegex(ExportValidationError, "had not closed"):
            validate_export(self.manifest_path)

    def test_rejects_invalid_ohlc_geometry(self) -> None:
        path = self.root / self.m15_name
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
            writer.writerow((self.m15_times[0], 4100, 4099, 4098, 4101, 10, 20, 0))
            writer.writerow((self.m15_times[1], 4101, 4103, 4099, 4102, 10, 20, 0))

        with self.assertRaisesRegex(ExportValidationError, "high is below"):
            validate_export(self.manifest_path)

    def test_rejects_a_material_server_timezone_offset(self) -> None:
        self.manifest["time_basis"]["server_minus_gmt_seconds"] = 7200
        self.write_manifest()

        with self.assertRaisesRegex(ExportValidationError, "within five seconds"):
            validate_export(self.manifest_path)

    def test_rejects_untrusted_account_metadata(self) -> None:
        baseline = copy.deepcopy(self.manifest)
        cases = (
            ("server", "Other-Demo", "expected an Exness server"),
            ("trade_mode", "real", "demo exports only"),
            ("profile", "Raw Spread", "expected 'Standard'"),
            ("profile_source", "user-input", "approved research contract"),
        )

        for field, value, message in cases:
            with self.subTest(field=field):
                self.manifest = copy.deepcopy(baseline)
                self.manifest["account"][field] = value
                self.write_manifest()
                with self.assertRaisesRegex(ExportValidationError, message):
                    validate_export(self.manifest_path)

    def test_rejects_a_tick_from_the_future(self) -> None:
        self.manifest["latest_tick"]["time_msc"] = (
            self.manifest["generated_at_epoch"] * 1000 + 6000
        )
        self.write_manifest()

        with self.assertRaisesRegex(ExportValidationError, "ahead"):
            validate_export(self.manifest_path)

    def test_rejects_a_csv_row_with_extra_fields(self) -> None:
        path = self.root / self.m15_name
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] += ",unexpected"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ExportValidationError, "different field count"):
            validate_export(self.manifest_path)


if __name__ == "__main__":
    unittest.main()
