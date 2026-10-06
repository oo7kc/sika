"""Validate resumable monthly history exported by ``SikaExportHistory.mq5``."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from ..configuration import ConfigurationError
from ..logging_config import command_logger
from .bar_csv import BarCsvValidationError, BarGap, audit_bar_csv

SCHEMA = "sika-mt5-backfill-month-v1"
EXPECTED_SYMBOL = "XAUUSDm"
EXPECTED_ACCOUNT_PROFILE = "Standard"
EXPECTED_PROFILE_SOURCE = "research-contract-v0.1"
EXPECTED_TIMEFRAMES = {"M1": 60, "M15": 15 * 60, "H1": 60 * 60}
DEFAULT_START_MONTH = "2021-10"
DEFAULT_END_MONTH_EXCLUSIVE = "2026-10"
MONTH_PATTERN = re.compile(r"^(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])$")


class BackfillValidationError(ValueError):
    """Raised when a history bundle violates the backfill contract."""


@dataclass(frozen=True)
class GapAudit:
    source_month: str
    classification: str
    after_time_epoch: int
    after_time_utc: str
    before_time_epoch: int
    before_time_utc: str
    interval_seconds: int
    missing_periods: int


@dataclass(frozen=True)
class MonthlyBarAudit:
    timeframe: str
    file: str
    sha256: str
    count: int
    first_time_epoch: int
    first_time_utc: str
    last_time_epoch: int
    last_time_utc: str
    gap_count: int


@dataclass(frozen=True)
class MonthlyBundleAudit:
    month: str
    manifest: str
    generated_at_epoch: int
    generated_at_utc: str
    terminal_build: int
    bars: dict[str, MonthlyBarAudit]


@dataclass(frozen=True)
class TimeframeCoverage:
    timeframe: str
    file_count: int
    bar_count: int
    first_time_epoch: int
    first_time_utc: str
    last_time_epoch: int
    last_time_utc: str
    weekend_closure_candidate_count: int
    rollover_closure_candidate_count: int
    closure_candidate_samples: tuple[GapAudit, ...]
    review_required_gaps: tuple[GapAudit, ...]


@dataclass(frozen=True)
class BackfillAudit:
    schema: str
    status: str
    symbol: str
    server: str
    account_company: str
    account_profile: str
    start_month: str
    end_month_exclusive: str
    month_count: int
    bundles: tuple[MonthlyBundleAudit, ...]
    coverage: dict[str, TimeframeCoverage]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _ValidatedBundle:
    audit: MonthlyBundleAudit
    server: str
    company: str
    profile: str
    point: float
    contract_size: float
    gaps: dict[str, tuple[BarGap, ...]]


def _fail(location: str, message: str) -> BackfillValidationError:
    return BackfillValidationError(f"{location}: {message}")


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
    result = float(value)
    if not math.isfinite(result):
        raise _fail(f"{location}.{key}", "must be finite")
    return result


def _boolean(record: Mapping[str, Any], key: str, location: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise _fail(f"{location}.{key}", "expected a boolean")
    return value


def _utc_iso(epoch: int) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise BackfillValidationError(f"invalid Unix timestamp: {epoch}") from exc


def parse_month(value: str) -> datetime:
    """Parse an exact ``YYYY-MM`` month boundary in UTC."""

    match = MONTH_PATTERN.fullmatch(value)
    if match is None:
        raise BackfillValidationError(f"invalid month {value!r}; expected YYYY-MM")
    return datetime(
        int(match.group("year")),
        int(match.group("month")),
        1,
        tzinfo=UTC,
    )


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _month_range(start: datetime, end_exclusive: datetime) -> tuple[datetime, ...]:
    if start >= end_exclusive:
        raise BackfillValidationError("start month must precede end month")
    months: list[datetime] = []
    current = start
    while current < end_exclusive:
        months.append(current)
        current = _next_month(current)
    return tuple(months)


def _safe_companion_path(parent: Path, filename: str, location: str) -> Path:
    candidate_name = Path(filename)
    if candidate_name.name != filename or candidate_name.is_absolute():
        raise _fail(location, "must be a plain filename without directories")
    candidate = parent / candidate_name
    if candidate.resolve().parent != parent.resolve():
        raise _fail(location, "escapes the monthly bundle directory")
    if not candidate.is_file():
        raise _fail(location, f"companion file does not exist: {filename}")
    return candidate


def _load_manifest(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise BackfillValidationError(f"missing monthly manifest: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackfillValidationError(f"cannot read manifest {path}: {exc}") from exc
    return _mapping(value, path.name)


def _validate_bundle(
    manifest_path: Path,
    *,
    month_start: datetime,
    month_end: datetime,
    expected_symbol: str,
) -> _ValidatedBundle:
    manifest = _load_manifest(manifest_path)
    month = month_start.strftime("%Y-%m")
    month_key = month_start.strftime("%Y%m")
    bundle_id = f"{month_key}_{expected_symbol}"
    location = manifest_path.name

    if _string(manifest, "schema", location) != SCHEMA:
        raise _fail(f"{location}.schema", f"must be {SCHEMA!r}")
    if not _boolean(manifest, "complete", location):
        raise _fail(f"{location}.complete", "must be true")
    if _string(manifest, "mode", location) != "read-only":
        raise _fail(f"{location}.mode", "must be 'read-only'")
    if _string(manifest, "bundle_id", location) != bundle_id:
        raise _fail(f"{location}.bundle_id", f"must be {bundle_id!r}")
    if _string(manifest, "month", location) != month:
        raise _fail(f"{location}.month", f"must be {month!r}")

    start_epoch = int(month_start.timestamp())
    end_epoch = int(month_end.timestamp())
    if _integer(manifest, "requested_start_epoch", location) != start_epoch:
        raise _fail(f"{location}.requested_start_epoch", "wrong month boundary")
    if _integer(manifest, "requested_end_exclusive_epoch", location) != end_epoch:
        raise _fail(
            f"{location}.requested_end_exclusive_epoch",
            "wrong exclusive month boundary",
        )
    generated_at = _integer(manifest, "generated_at_epoch", location)
    if generated_at < end_epoch:
        raise _fail(f"{location}.generated_at_epoch", "month was not complete")
    _utc_iso(generated_at)

    time_basis = _mapping(manifest.get("time_basis"), f"{location}.time_basis")
    if _string(time_basis, "server_clock_source", f"{location}.time_basis") != (
        "TimeTradeServer"
    ):
        raise _fail(
            f"{location}.time_basis.server_clock_source",
            "must be 'TimeTradeServer'",
        )
    server_delta = _integer(
        time_basis, "server_minus_gmt_seconds", f"{location}.time_basis"
    )
    if abs(server_delta) > 5:
        raise _fail(
            f"{location}.time_basis.server_minus_gmt_seconds",
            "must be within five seconds of UTC",
        )

    terminal = _mapping(manifest.get("terminal"), f"{location}.terminal")
    if not _boolean(terminal, "connected", f"{location}.terminal"):
        raise _fail(f"{location}.terminal.connected", "must be true")
    terminal_build = _integer(terminal, "build", f"{location}.terminal")

    account = _mapping(manifest.get("account"), f"{location}.account")
    server = _string(account, "server", f"{location}.account")
    company = _string(account, "company", f"{location}.account")
    if not server.startswith("Exness-") or "Exness" not in company:
        raise _fail(f"{location}.account", "expected an Exness server and company")
    if _string(account, "trade_mode", f"{location}.account") != "demo":
        raise _fail(f"{location}.account.trade_mode", "demo exports only")
    profile = _string(account, "profile", f"{location}.account")
    if profile != EXPECTED_ACCOUNT_PROFILE:
        raise _fail(
            f"{location}.account.profile",
            f"expected {EXPECTED_ACCOUNT_PROFILE!r}, received {profile!r}",
        )
    if _string(account, "profile_source", f"{location}.account") != (
        EXPECTED_PROFILE_SOURCE
    ):
        raise _fail(
            f"{location}.account.profile_source",
            "must identify the approved research contract",
        )

    symbol = _mapping(manifest.get("symbol"), f"{location}.symbol")
    symbol_name = _string(symbol, "name", f"{location}.symbol")
    if symbol_name != expected_symbol:
        raise _fail(
            f"{location}.symbol.name",
            f"expected {expected_symbol!r}, received {symbol_name!r}",
        )
    point = _number(symbol, "point", f"{location}.symbol")
    contract_size = _number(symbol, "contract_size", f"{location}.symbol")
    if point <= 0 or contract_size <= 0:
        raise _fail(f"{location}.symbol", "point and contract size must be positive")

    bars = _mapping(manifest.get("bars"), f"{location}.bars")
    if set(bars) != set(EXPECTED_TIMEFRAMES):
        raise _fail(
            f"{location}.bars",
            "must contain exactly M1, M15, and H1",
        )

    bar_audits: dict[str, MonthlyBarAudit] = {}
    gaps: dict[str, tuple[BarGap, ...]] = {}
    for timeframe, timeframe_seconds in EXPECTED_TIMEFRAMES.items():
        bar_location = f"{location}.bars.{timeframe}"
        bar = _mapping(bars.get(timeframe), bar_location)
        if _integer(bar, "timeframe_seconds", bar_location) != timeframe_seconds:
            raise _fail(
                f"{bar_location}.timeframe_seconds",
                f"must be {timeframe_seconds}",
            )
        if not _boolean(bar, "closed_bars_only", bar_location):
            raise _fail(f"{bar_location}.closed_bars_only", "must be true")

        filename = _string(bar, "file", bar_location)
        expected_filename = f"{bundle_id}_{timeframe}.csv"
        if filename != expected_filename:
            raise _fail(f"{bar_location}.file", f"must be {expected_filename!r}")
        csv_path = _safe_companion_path(
            manifest_path.parent,
            filename,
            f"{bar_location}.file",
        )
        count = _integer(bar, "count", bar_location)
        first = _integer(bar, "first_time_epoch", bar_location)
        last = _integer(bar, "last_time_epoch", bar_location)
        try:
            csv_audit = audit_bar_csv(
                csv_path,
                timeframe_seconds=timeframe_seconds,
                expected_count=count,
                expected_first_time=first,
                expected_last_time=last,
                earliest_open_time=start_epoch,
                latest_open_time_exclusive=end_epoch,
                closed_before_or_at=generated_at,
            )
        except BarCsvValidationError as exc:
            raise BackfillValidationError(str(exc)) from exc

        bar_audits[timeframe] = MonthlyBarAudit(
            timeframe=timeframe,
            file=csv_audit.file,
            sha256=csv_audit.sha256,
            count=csv_audit.count,
            first_time_epoch=csv_audit.first_time_epoch,
            first_time_utc=_utc_iso(csv_audit.first_time_epoch),
            last_time_epoch=csv_audit.last_time_epoch,
            last_time_utc=_utc_iso(csv_audit.last_time_epoch),
            gap_count=len(csv_audit.gaps),
        )
        gaps[timeframe] = csv_audit.gaps

    return _ValidatedBundle(
        audit=MonthlyBundleAudit(
            month=month,
            manifest=str(manifest_path),
            generated_at_epoch=generated_at,
            generated_at_utc=_utc_iso(generated_at),
            terminal_build=terminal_build,
            bars=bar_audits,
        ),
        server=server,
        company=company,
        profile=profile,
        point=point,
        contract_size=contract_size,
        gaps=gaps,
    )


def _is_weekend_closure_candidate(start: datetime, end: datetime) -> bool:
    if end - start > timedelta(hours=72):
        return False
    if start.weekday() == 4:
        return start.hour >= 18 and end.weekday() == 6 and end.hour >= 18
    if start.weekday() == 5:
        return end.weekday() == 6 and end.hour >= 18
    if start.weekday() == 6:
        return start.date() == end.date() and end.hour >= 18
    return False


def _overlaps_rollover(start: datetime, end: datetime) -> bool:
    current: date = start.date()
    while current <= end.date():
        if current.weekday() in {0, 1, 2, 3}:
            for hour in (21, 22):
                boundary = datetime.combine(current, time(hour=hour), tzinfo=UTC)
                if start <= boundary <= end:
                    return True
        current += timedelta(days=1)
    return False


def _classify_gap(gap: BarGap, timeframe_seconds: int) -> str:
    missing_start = datetime.fromtimestamp(
        gap.after_time_epoch + timeframe_seconds,
        tz=UTC,
    )
    next_bar = datetime.fromtimestamp(gap.before_time_epoch, tz=UTC)
    if _is_weekend_closure_candidate(missing_start, next_bar):
        return "weekend_closure_candidate"
    if (
        gap.interval_seconds <= timeframe_seconds + 3 * 60 * 60
        and _overlaps_rollover(missing_start, next_bar)
    ):
        return "rollover_closure_candidate"
    return "review_required"


def _gap_audit(
    gap: BarGap,
    *,
    source_month: str,
    timeframe_seconds: int,
) -> GapAudit:
    return GapAudit(
        source_month=source_month,
        classification=_classify_gap(gap, timeframe_seconds),
        after_time_epoch=gap.after_time_epoch,
        after_time_utc=_utc_iso(gap.after_time_epoch),
        before_time_epoch=gap.before_time_epoch,
        before_time_utc=_utc_iso(gap.before_time_epoch),
        interval_seconds=gap.interval_seconds,
        missing_periods=gap.interval_seconds // timeframe_seconds - 1,
    )


def validate_backfill(
    root: str | Path,
    *,
    start_month: str = DEFAULT_START_MONTH,
    end_month_exclusive: str = DEFAULT_END_MONTH_EXCLUSIVE,
    expected_symbol: str = EXPECTED_SYMBOL,
) -> BackfillAudit:
    """Validate every expected monthly bundle and summarize range continuity."""

    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        raise BackfillValidationError(f"backfill root does not exist: {root_path}")
    start = parse_month(start_month)
    end = parse_month(end_month_exclusive)
    months = _month_range(start, end)

    bundles: list[_ValidatedBundle] = []
    for month_start in months:
        month_end = _next_month(month_start)
        month_key = month_start.strftime("%Y%m")
        manifest = (
            root_path
            / month_key
            / f"{month_key}_{expected_symbol}_manifest.json"
        )
        bundles.append(
            _validate_bundle(
                manifest,
                month_start=month_start,
                month_end=month_end,
                expected_symbol=expected_symbol,
            )
        )

    first_bundle = bundles[0]
    for bundle in bundles[1:]:
        if (
            bundle.server != first_bundle.server
            or bundle.company != first_bundle.company
            or bundle.profile != first_bundle.profile
        ):
            raise _fail(bundle.audit.manifest, "account provenance changed across months")
        if (
            bundle.point != first_bundle.point
            or bundle.contract_size != first_bundle.contract_size
        ):
            raise _fail(bundle.audit.manifest, "symbol specification changed across months")

    coverage: dict[str, TimeframeCoverage] = {}
    for timeframe, timeframe_seconds in EXPECTED_TIMEFRAMES.items():
        all_gaps: list[GapAudit] = []
        range_start_epoch = int(start.timestamp())
        range_end_epoch = int(end.timestamp())
        previous_last = range_start_epoch - timeframe_seconds
        total_bars = 0
        for bundle in bundles:
            bar = bundle.audit.bars[timeframe]
            delta = bar.first_time_epoch - previous_last
            if delta <= 0:
                raise _fail(
                    bundle.audit.manifest,
                    f"{timeframe} overlaps or reverses the preceding month",
                )
            if delta % timeframe_seconds:
                raise _fail(
                    bundle.audit.manifest,
                    f"{timeframe} boundary is not aligned to its period",
                )
            if delta > timeframe_seconds:
                all_gaps.append(
                    _gap_audit(
                        BarGap(previous_last, bar.first_time_epoch, delta),
                        source_month=bundle.audit.month,
                        timeframe_seconds=timeframe_seconds,
                    )
                )
            all_gaps.extend(
                _gap_audit(
                    gap,
                    source_month=bundle.audit.month,
                    timeframe_seconds=timeframe_seconds,
                )
                for gap in bundle.gaps[timeframe]
            )
            previous_last = bar.last_time_epoch
            total_bars += bar.count

        trailing_delta = range_end_epoch - previous_last
        if trailing_delta <= 0 or trailing_delta % timeframe_seconds:
            raise _fail(
                bundles[-1].audit.manifest,
                f"{timeframe} has an invalid final range boundary",
            )
        if trailing_delta > timeframe_seconds:
            all_gaps.append(
                _gap_audit(
                    BarGap(previous_last, range_end_epoch, trailing_delta),
                    source_month=bundles[-1].audit.month,
                    timeframe_seconds=timeframe_seconds,
                )
            )

        weekend = tuple(
            gap for gap in all_gaps if gap.classification == "weekend_closure_candidate"
        )
        rollover = tuple(
            gap
            for gap in all_gaps
            if gap.classification == "rollover_closure_candidate"
        )
        review = tuple(
            gap for gap in all_gaps if gap.classification == "review_required"
        )
        closure_samples = (weekend + rollover)[:20]
        first_bar = bundles[0].audit.bars[timeframe]
        last_bar = bundles[-1].audit.bars[timeframe]
        coverage[timeframe] = TimeframeCoverage(
            timeframe=timeframe,
            file_count=len(bundles),
            bar_count=total_bars,
            first_time_epoch=first_bar.first_time_epoch,
            first_time_utc=first_bar.first_time_utc,
            last_time_epoch=last_bar.last_time_epoch,
            last_time_utc=last_bar.last_time_utc,
            weekend_closure_candidate_count=len(weekend),
            rollover_closure_candidate_count=len(rollover),
            closure_candidate_samples=closure_samples,
            review_required_gaps=review,
        )

    status = (
        "review_required"
        if any(item.review_required_gaps for item in coverage.values())
        else "structurally_valid"
    )
    return BackfillAudit(
        schema=SCHEMA,
        status=status,
        symbol=expected_symbol,
        server=first_bundle.server,
        account_company=first_bundle.company,
        account_profile=first_bundle.profile,
        start_month=start_month,
        end_month_exclusive=end_month_exclusive,
        month_count=len(bundles),
        bundles=tuple(bundle.audit for bundle in bundles),
        coverage=coverage,
    )


def write_report(audit: BackfillAudit, output: Path) -> None:
    """Write a validation receipt atomically."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(audit.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the complete Sika monthly MT5 history backfill."
    )
    parser.add_argument("root", type=Path, help="MT5 Sika/backfill directory")
    parser.add_argument("--start-month", default=DEFAULT_START_MONTH)
    parser.add_argument(
        "--end-month-exclusive",
        default=DEFAULT_END_MONTH_EXCLUSIVE,
        help="First month not included in the backfill",
    )
    parser.add_argument("--expected-symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--output", type=Path, help="Optional JSON validation receipt")
    parser.add_argument("--json", action="store_true", help="Print the full receipt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        logger = command_logger("mt5_validate_backfill")
    except (ConfigurationError, OSError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return 2

    logger.info("backfill validation started", extra={"event": "validation_started"})
    try:
        audit = validate_backfill(
            args.root,
            start_month=args.start_month,
            end_month_exclusive=args.end_month_exclusive,
            expected_symbol=args.expected_symbol,
        )
        if args.output:
            write_report(audit, args.output)
    except (BackfillValidationError, OSError) as exc:
        logger.error(
            "backfill validation failed: %s",
            exc,
            extra={"event": "validation_failed"},
        )
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(audit.as_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"{audit.status.upper()} {audit.symbol}: {audit.month_count} months "
            f"from {audit.start_month} to {audit.end_month_exclusive} (exclusive)"
        )
        for timeframe in EXPECTED_TIMEFRAMES:
            item = audit.coverage[timeframe]
            print(
                f"{timeframe}: {item.bar_count} bars, "
                f"{item.first_time_utc} -> {item.last_time_utc}, "
                f"review_gaps={len(item.review_required_gaps)}"
            )
    if audit.status == "review_required":
        logger.warning(
            "backfill validation completed with status review_required",
            extra={"event": "validation_completed"},
        )
        print(
            "REVIEW REQUIRED: reconcile the listed gaps with historical "
            "holiday/maintenance schedules before research use.",
            file=sys.stderr,
        )
        return 3
    logger.info(
        "backfill validation completed with status structurally_valid",
        extra={"event": "validation_completed"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
