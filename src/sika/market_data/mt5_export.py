"""Validate a completed export produced by ``SikaExportBars.mq5``.

The validator is intentionally independent of MetaTrader. It treats the manifest
as a completion marker, resolves its companion CSV files without permitting path
escape, and streams every row through the current research-contract invariants.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


EXPECTED_COLUMNS = (
    "time_epoch",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread_points",
    "real_volume",
)
EXPECTED_TIMEFRAMES = {"M15": 15 * 60, "H1": 60 * 60}
SCHEMA_VERSION = 2
EXPECTED_ACCOUNT_PROFILE = "Standard"


class ExportValidationError(ValueError):
    """Raised when an MT5 export does not satisfy the data contract."""


@dataclass(frozen=True)
class BarAudit:
    timeframe: str
    file: str
    sha256: str
    count: int
    first_time_epoch: int
    first_time_utc: str
    last_time_epoch: int
    last_time_utc: str
    gap_count: int
    largest_gap_seconds: int


@dataclass(frozen=True)
class ExportAudit:
    schema_version: int
    export_id: str
    symbol: str
    server: str
    account_company: str
    account_profile: str
    terminal_build: int
    generated_at_epoch: int
    generated_at_utc: str
    server_minus_gmt_seconds: int
    tick_age_seconds: float
    bars: dict[str, BarAudit]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fail(location: str, message: str) -> ExportValidationError:
    return ExportValidationError(f"{location}: {message}")


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(location, "expected an object")
    return value


def _string(record: Mapping[str, Any], key: str, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise _fail(f"{location}.{key}", "expected a non-empty string")
    return value


def _integer(record: Mapping[str, Any], key: str, location: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{location}.{key}", "expected an integer")
    return value


def _number(record: Mapping[str, Any], key: str, location: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{location}.{key}", "expected a number")
    number = float(value)
    if not math.isfinite(number):
        raise _fail(f"{location}.{key}", "must be finite")
    return number


def _boolean(record: Mapping[str, Any], key: str, location: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise _fail(f"{location}.{key}", "expected a boolean")
    return value


def _utc_iso(epoch: int) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise ExportValidationError(f"invalid Unix timestamp: {epoch}") from exc


def _safe_companion_path(parent: Path, filename: str, location: str) -> Path:
    candidate_name = Path(filename)
    if candidate_name.name != filename or candidate_name.is_absolute():
        raise _fail(location, "must be a plain filename without directories")
    candidate = parent / candidate_name
    if candidate.resolve().parent != parent.resolve():
        raise _fail(location, "escapes the manifest directory")
    if not candidate.is_file():
        raise _fail(location, f"companion file does not exist: {filename}")
    return candidate


def _parse_integer(value: str | None, location: str) -> int:
    if value is None:
        raise _fail(location, "missing value")
    try:
        return int(value)
    except ValueError as exc:
        raise _fail(location, f"invalid integer {value!r}") from exc


def _parse_decimal(value: str | None, location: str) -> Decimal:
    if value is None:
        raise _fail(location, "missing value")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise _fail(location, f"invalid decimal {value!r}") from exc
    if not result.is_finite():
        raise _fail(location, "must be finite")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_csv(
    path: Path,
    timeframe: str,
    timeframe_seconds: int,
    manifest_bar: Mapping[str, Any],
    generated_at_epoch: int,
) -> BarAudit:
    expected_count = _integer(manifest_bar, "count", f"bars.{timeframe}")
    if expected_count <= 0:
        raise _fail(f"bars.{timeframe}.count", "must be positive")

    first_timestamp: int | None = None
    previous_timestamp: int | None = None
    last_timestamp: int | None = None
    gap_count = 0
    largest_gap = timeframe_seconds
    count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise _fail(
                path.name,
                f"columns must be exactly {','.join(EXPECTED_COLUMNS)}",
            )

        for line_number, row in enumerate(reader, start=2):
            location = f"{path.name}:{line_number}"
            if None in row or len(row) != len(EXPECTED_COLUMNS):
                raise _fail(location, "row has a different field count than the header")
            timestamp = _parse_integer(row.get("time_epoch"), f"{location}.time_epoch")
            prices = {
                name: _parse_decimal(row.get(name), f"{location}.{name}")
                for name in ("open", "high", "low", "close")
            }
            tick_volume = _parse_integer(
                row.get("tick_volume"), f"{location}.tick_volume"
            )
            spread = _parse_integer(
                row.get("spread_points"), f"{location}.spread_points"
            )
            real_volume = _parse_integer(
                row.get("real_volume"), f"{location}.real_volume"
            )

            if timestamp <= 0:
                raise _fail(f"{location}.time_epoch", "must be positive")
            if timestamp % timeframe_seconds:
                raise _fail(
                    f"{location}.time_epoch",
                    f"is not aligned to a {timeframe_seconds}-second boundary",
                )
            if any(price <= 0 for price in prices.values()):
                raise _fail(location, "OHLC prices must be positive")
            if prices["low"] > min(prices["open"], prices["close"]):
                raise _fail(location, "low exceeds open or close")
            if prices["high"] < max(prices["open"], prices["close"]):
                raise _fail(location, "high is below open or close")
            if prices["high"] < prices["low"]:
                raise _fail(location, "high is below low")
            if tick_volume < 0 or spread < 0 or real_volume < 0:
                raise _fail(location, "volume and spread fields cannot be negative")

            if previous_timestamp is not None:
                delta = timestamp - previous_timestamp
                if delta <= 0:
                    raise _fail(location, "timestamps are not strictly increasing")
                if delta % timeframe_seconds:
                    raise _fail(
                        location,
                        "interval is not a whole number of timeframe periods",
                    )
                if delta > timeframe_seconds:
                    gap_count += 1
                    largest_gap = max(largest_gap, delta)

            if first_timestamp is None:
                first_timestamp = timestamp
            previous_timestamp = timestamp
            last_timestamp = timestamp
            count += 1

    if count != expected_count:
        raise _fail(path.name, f"contains {count} rows; manifest declares {expected_count}")
    if first_timestamp is None or last_timestamp is None:
        raise _fail(path.name, "contains no data rows")

    declared_first = _integer(
        manifest_bar, "first_time_epoch", f"bars.{timeframe}"
    )
    declared_last = _integer(manifest_bar, "last_time_epoch", f"bars.{timeframe}")
    if first_timestamp != declared_first:
        raise _fail(path.name, "first timestamp differs from the manifest")
    if last_timestamp != declared_last:
        raise _fail(path.name, "last timestamp differs from the manifest")
    if not _boolean(
        manifest_bar, "forming_bar_excluded", f"bars.{timeframe}"
    ):
        raise _fail(f"bars.{timeframe}", "forming_bar_excluded must be true")
    if last_timestamp + timeframe_seconds > generated_at_epoch:
        raise _fail(path.name, "latest bar had not closed when the manifest was written")

    return BarAudit(
        timeframe=timeframe,
        file=path.name,
        sha256=_sha256(path),
        count=count,
        first_time_epoch=first_timestamp,
        first_time_utc=_utc_iso(first_timestamp),
        last_time_epoch=last_timestamp,
        last_time_utc=_utc_iso(last_timestamp),
        gap_count=gap_count,
        largest_gap_seconds=largest_gap,
    )


def validate_export(
    manifest_path: str | Path, *, expected_symbol: str = "XAUUSDm"
) -> ExportAudit:
    """Validate one completed manifest and both of its closed-bar CSV files."""

    path = Path(manifest_path).expanduser()
    if not path.is_file():
        raise ExportValidationError(f"manifest does not exist: {path}")
    try:
        manifest_object = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportValidationError(f"cannot read manifest {path}: {exc}") from exc
    manifest = _mapping(manifest_object, "manifest")

    schema_version = _integer(manifest, "schema_version", "manifest")
    if schema_version != SCHEMA_VERSION:
        raise _fail(
            "manifest.schema_version",
            f"only schema version {SCHEMA_VERSION} is supported",
        )
    if not _boolean(manifest, "complete", "manifest"):
        raise _fail("manifest.complete", "must be true")
    if _string(manifest, "mode", "manifest") != "read-only":
        raise _fail("manifest.mode", "must be 'read-only'")

    export_id = _string(manifest, "export_id", "manifest")
    generated_at = _integer(manifest, "generated_at_epoch", "manifest")
    _utc_iso(generated_at)

    terminal = _mapping(manifest.get("terminal"), "terminal")
    if not _boolean(terminal, "connected", "terminal"):
        raise _fail("terminal.connected", "terminal was disconnected during export")
    terminal_build = _integer(terminal, "build", "terminal")

    account = _mapping(manifest.get("account"), "account")
    server = _string(account, "server", "account")
    account_company = _string(account, "company", "account")
    if not server.startswith("Exness-") or "Exness" not in account_company:
        raise _fail("account", "expected an Exness server and company")
    if _string(account, "trade_mode", "account") != "demo":
        raise _fail(
            "account.trade_mode",
            "the v0 research contract accepts demo exports only",
        )
    account_profile = _string(account, "profile", "account")
    if account_profile != EXPECTED_ACCOUNT_PROFILE:
        raise _fail(
            "account.profile",
            f"expected {EXPECTED_ACCOUNT_PROFILE!r}, received {account_profile!r}",
        )
    if _string(account, "profile_source", "account") != "research-contract-v0.1":
        raise _fail(
            "account.profile_source",
            "must identify the approved research contract",
        )

    symbol_record = _mapping(manifest.get("symbol"), "symbol")
    symbol = _string(symbol_record, "name", "symbol")
    if symbol != expected_symbol:
        raise _fail("symbol.name", f"expected {expected_symbol!r}, received {symbol!r}")
    point = _number(symbol_record, "point", "symbol")
    contract_size = _number(symbol_record, "contract_size", "symbol")
    if point <= 0 or contract_size <= 0:
        raise _fail("symbol", "point and contract size must be positive")

    expected_manifest_name = f"{export_id}_{symbol}_manifest.json"
    if path.name != expected_manifest_name:
        raise _fail("manifest", f"filename must be {expected_manifest_name!r}")

    time_basis = _mapping(manifest.get("time_basis"), "time_basis")
    server_delta = _integer(
        time_basis, "server_minus_gmt_seconds", "time_basis"
    )

    tick = _mapping(manifest.get("latest_tick"), "latest_tick")
    tick_time_msc = _integer(tick, "time_msc", "latest_tick")
    bid = _number(tick, "bid", "latest_tick")
    ask = _number(tick, "ask", "latest_tick")
    if tick_time_msc <= 0 or bid <= 0 or ask < bid:
        raise _fail("latest_tick", "invalid tick time or bid/ask")
    tick_age_seconds = (generated_at * 1000 - tick_time_msc) / 1000

    if abs(server_delta) > 5:
        raise _fail(
            "time_basis.server_minus_gmt_seconds",
            "must be within five seconds of UTC for the Exness v0 contract",
        )
    if tick_age_seconds < -5:
        raise _fail(
            "latest_tick.time_msc",
            "was materially ahead of the exporter clock",
        )

    warnings: list[str] = []
    if tick_age_seconds > 30:
        warnings.append("latest tick was more than 30 seconds old at export time")

    bars_record = _mapping(manifest.get("bars"), "bars")
    bar_audits: dict[str, BarAudit] = {}
    for timeframe, expected_seconds in EXPECTED_TIMEFRAMES.items():
        manifest_bar = _mapping(bars_record.get(timeframe), f"bars.{timeframe}")
        declared_seconds = _integer(
            manifest_bar, "timeframe_seconds", f"bars.{timeframe}"
        )
        if declared_seconds != expected_seconds:
            raise _fail(
                f"bars.{timeframe}.timeframe_seconds",
                f"expected {expected_seconds}, received {declared_seconds}",
            )
        filename = _string(manifest_bar, "file", f"bars.{timeframe}")
        expected_filename = f"{export_id}_{symbol}_{timeframe}.csv"
        if filename != expected_filename:
            raise _fail(
                f"bars.{timeframe}.file", f"must be {expected_filename!r}"
            )
        csv_path = _safe_companion_path(
            path.parent, filename, f"bars.{timeframe}.file"
        )
        bar_audits[timeframe] = _audit_csv(
            csv_path,
            timeframe,
            expected_seconds,
            manifest_bar,
            generated_at,
        )

    return ExportAudit(
        schema_version=schema_version,
        export_id=export_id,
        symbol=symbol,
        server=server,
        account_company=account_company,
        account_profile=account_profile,
        terminal_build=terminal_build,
        generated_at_epoch=generated_at,
        generated_at_utc=_utc_iso(generated_at),
        server_minus_gmt_seconds=server_delta,
        tick_age_seconds=round(tick_age_seconds, 3),
        bars=bar_audits,
        warnings=tuple(warnings),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completed Sika MQL5 closed-bar export."
    )
    parser.add_argument("manifest", type=Path, help="Path to the export manifest")
    parser.add_argument(
        "--expected-symbol",
        default="XAUUSDm",
        help="Exact broker symbol allowed by this research run (default: XAUUSDm)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the validation receipt as JSON"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        audit = validate_export(args.manifest, expected_symbol=args.expected_symbol)
    except ExportValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(audit.as_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"VALID {audit.export_id} {audit.symbol} "
            f"({audit.server}, terminal build {audit.terminal_build})"
        )
        for timeframe in EXPECTED_TIMEFRAMES:
            bars = audit.bars[timeframe]
            print(
                f"{timeframe}: {bars.count} closed bars, "
                f"{bars.first_time_utc} -> {bars.last_time_utc}, "
                f"gaps={bars.gap_count}, sha256={bars.sha256}"
            )
        for warning in audit.warnings:
            print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
