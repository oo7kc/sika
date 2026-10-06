"""Shared validation for chronological MT5 bar CSV files."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


BAR_COLUMNS = (
    "time_epoch",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread_points",
    "real_volume",
)


class BarCsvValidationError(ValueError):
    """Raised when a bar file violates the shared market-data contract."""


@dataclass(frozen=True)
class BarGap:
    after_time_epoch: int
    before_time_epoch: int
    interval_seconds: int


@dataclass(frozen=True)
class BarCsvAudit:
    file: str
    sha256: str
    count: int
    first_time_epoch: int
    last_time_epoch: int
    gaps: tuple[BarGap, ...]


def _fail(location: str, message: str) -> BarCsvValidationError:
    return BarCsvValidationError(f"{location}: {message}")


def _integer(value: str | None, location: str) -> int:
    if value is None:
        raise _fail(location, "missing value")
    try:
        return int(value)
    except ValueError as exc:
        raise _fail(location, f"invalid integer {value!r}") from exc


def _decimal(value: str | None, location: str) -> Decimal:
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


def audit_bar_csv(
    path: Path,
    *,
    timeframe_seconds: int,
    expected_count: int,
    expected_first_time: int,
    expected_last_time: int,
    earliest_open_time: int | None = None,
    latest_open_time_exclusive: int | None = None,
    closed_before_or_at: int | None = None,
) -> BarCsvAudit:
    """Stream and validate one exact, chronological closed-bar file."""

    if timeframe_seconds <= 0:
        raise ValueError("timeframe_seconds must be positive")
    if expected_count <= 0:
        raise _fail(path.name, "manifest count must be positive")

    first_timestamp: int | None = None
    previous_timestamp: int | None = None
    last_timestamp: int | None = None
    gaps: list[BarGap] = []
    count = 0

    try:
        stream = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise _fail(path.name, f"cannot open bar file: {exc}") from exc

    with stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != BAR_COLUMNS:
            raise _fail(path.name, f"columns must be exactly {','.join(BAR_COLUMNS)}")

        for line_number, row in enumerate(reader, start=2):
            location = f"{path.name}:{line_number}"
            if None in row or len(row) != len(BAR_COLUMNS):
                raise _fail(location, "row has a different field count than the header")

            timestamp = _integer(row.get("time_epoch"), f"{location}.time_epoch")
            prices = {
                name: _decimal(row.get(name), f"{location}.{name}")
                for name in ("open", "high", "low", "close")
            }
            tick_volume = _integer(
                row.get("tick_volume"), f"{location}.tick_volume"
            )
            spread = _integer(row.get("spread_points"), f"{location}.spread_points")
            real_volume = _integer(
                row.get("real_volume"), f"{location}.real_volume"
            )

            if timestamp <= 0:
                raise _fail(f"{location}.time_epoch", "must be positive")
            if timestamp % timeframe_seconds:
                raise _fail(
                    f"{location}.time_epoch",
                    f"is not aligned to a {timeframe_seconds}-second boundary",
                )
            if earliest_open_time is not None and timestamp < earliest_open_time:
                raise _fail(f"{location}.time_epoch", "precedes the requested range")
            if (
                latest_open_time_exclusive is not None
                and timestamp >= latest_open_time_exclusive
            ):
                raise _fail(f"{location}.time_epoch", "falls outside the requested range")
            if (
                closed_before_or_at is not None
                and timestamp + timeframe_seconds > closed_before_or_at
            ):
                raise _fail(location, "bar had not closed by the declared cutoff")

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
                    gaps.append(
                        BarGap(
                            after_time_epoch=previous_timestamp,
                            before_time_epoch=timestamp,
                            interval_seconds=delta,
                        )
                    )

            if first_timestamp is None:
                first_timestamp = timestamp
            previous_timestamp = timestamp
            last_timestamp = timestamp
            count += 1

    if count != expected_count:
        raise _fail(path.name, f"contains {count} rows; manifest declares {expected_count}")
    if first_timestamp is None or last_timestamp is None:
        raise _fail(path.name, "contains no data rows")
    if first_timestamp != expected_first_time:
        raise _fail(path.name, "first timestamp differs from the manifest")
    if last_timestamp != expected_last_time:
        raise _fail(path.name, "last timestamp differs from the manifest")

    try:
        digest = _sha256(path)
    except OSError as exc:
        raise _fail(path.name, f"cannot checksum bar file: {exc}") from exc

    return BarCsvAudit(
        file=path.name,
        sha256=digest,
        count=count,
        first_time_epoch=first_timestamp,
        last_time_epoch=last_timestamp,
        gaps=tuple(gaps),
    )
