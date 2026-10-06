"""Reconcile validated MT5 bar gaps against a versioned closure calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..configuration import ConfigurationError
from ..logging_config import command_logger
from .mt5_backfill import (
    DEFAULT_END_MONTH_EXCLUSIVE,
    DEFAULT_START_MONTH,
    EXPECTED_SYMBOL,
    EXPECTED_TIMEFRAMES,
    BackfillAudit,
    BackfillValidationError,
    GapAudit,
    validate_backfill,
)

CALENDAR_SCHEMA = "sika-xauusdm-closure-calendar-v1"
REPORT_SCHEMA = "sika-mt5-gap-reconciliation-v1"
NEW_YORK_TIMEZONE = "America/New_York"
OPERATING_START = time(8, 0)
OPERATING_END = time(16, 0)
CANDIDATE_START = time(8, 15)
CANDIDATE_END = time(14, 0)


class GapReconciliationError(ValueError):
    """Raised when closure evidence or a reconciliation input is invalid."""


@dataclass(frozen=True)
class CalendarSource:
    source_id: str
    title: str
    url: str
    scope: str


@dataclass(frozen=True)
class ClosureEvent:
    date: str
    name: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClosureCalendar:
    schema: str
    symbol: str
    timezone: str
    coverage_start_date: str
    coverage_end_date_exclusive: str
    sources: tuple[CalendarSource, ...]
    closures: tuple[ClosureEvent, ...]
    sha256: str


@dataclass(frozen=True)
class ReconciledGap:
    timeframe: str
    source_month: str
    resolution: str
    matched_closures: tuple[str, ...]
    after_time_epoch: int
    after_time_utc: str
    before_time_epoch: int
    before_time_utc: str
    missing_start_epoch: int
    missing_start_utc: str
    missing_periods: int
    operating_window_overlap: bool
    candidate_window_overlap: bool
    affected_new_york_dates: tuple[str, ...]
    quarantine_session_dates: tuple[str, ...]


@dataclass(frozen=True)
class TimeframeReconciliation:
    timeframe: str
    review_gap_count: int
    calendar_correlated_count: int
    quarantined_in_session_count: int
    quarantined_out_of_session_count: int
    gaps: tuple[ReconciledGap, ...]


@dataclass(frozen=True)
class GapReconciliation:
    schema: str
    status: str
    symbol: str
    server: str
    backfill_schema: str
    backfill_status: str
    start_month: str
    end_month_exclusive: str
    calendar_schema: str
    calendar_sha256: str
    calendar_sources: tuple[CalendarSource, ...]
    calendar_exclusion_dates: tuple[str, ...]
    observed_abnormal_session_dates: tuple[str, ...]
    quarantine_session_dates: tuple[str, ...]
    excluded_session_dates: tuple[str, ...]
    coverage: dict[str, TimeframeReconciliation]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GapReconciliationError(f"{location}: expected an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], location: str) -> None:
    if set(value) != expected:
        raise GapReconciliationError(
            f"{location}: expected keys {sorted(expected)}, received {sorted(value)}"
        )


def _string(value: Mapping[str, Any], key: str, location: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise GapReconciliationError(f"{location}.{key}: expected a string")
    return item


def _parse_date(value: str, location: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise GapReconciliationError(
            f"{location}: expected an ISO date, received {value!r}"
        ) from exc
    if parsed.isoformat() != value:
        raise GapReconciliationError(f"{location}: date must use YYYY-MM-DD")
    return parsed


def load_closure_calendar(path: str | Path) -> ClosureCalendar:
    """Load and strictly validate a versioned closure calendar."""

    calendar_path = Path(path)
    try:
        raw_bytes = calendar_path.read_bytes()
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GapReconciliationError(
            f"cannot read closure calendar {calendar_path}: {exc}"
        ) from exc

    root = _mapping(raw, "calendar")
    _exact_keys(
        root,
        {
            "schema",
            "symbol",
            "timezone",
            "coverage_start_date",
            "coverage_end_date_exclusive",
            "sources",
            "closures",
        },
        "calendar",
    )
    schema = _string(root, "schema", "calendar")
    if schema != CALENDAR_SCHEMA:
        raise GapReconciliationError(
            f"calendar.schema: expected {CALENDAR_SCHEMA!r}, received {schema!r}"
        )
    symbol = _string(root, "symbol", "calendar")
    timezone = _string(root, "timezone", "calendar")
    if timezone != NEW_YORK_TIMEZONE:
        raise GapReconciliationError(
            f"calendar.timezone: expected {NEW_YORK_TIMEZONE!r}"
        )
    coverage_start = _string(root, "coverage_start_date", "calendar")
    coverage_end = _string(root, "coverage_end_date_exclusive", "calendar")
    start_date = _parse_date(coverage_start, "calendar.coverage_start_date")
    end_date = _parse_date(coverage_end, "calendar.coverage_end_date_exclusive")
    if start_date >= end_date:
        raise GapReconciliationError("calendar coverage must have a positive range")

    raw_sources = root.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise GapReconciliationError("calendar.sources: expected a non-empty list")
    sources: list[CalendarSource] = []
    source_ids: set[str] = set()
    for index, item in enumerate(raw_sources):
        location = f"calendar.sources[{index}]"
        source = _mapping(item, location)
        _exact_keys(source, {"id", "title", "url", "scope"}, location)
        source_id = _string(source, "id", location)
        if source_id in source_ids:
            raise GapReconciliationError(f"{location}.id: duplicate {source_id!r}")
        url = _string(source, "url", location)
        if not url.startswith("https://"):
            raise GapReconciliationError(f"{location}.url: HTTPS is required")
        source_ids.add(source_id)
        sources.append(
            CalendarSource(
                source_id=source_id,
                title=_string(source, "title", location),
                url=url,
                scope=_string(source, "scope", location),
            )
        )

    raw_closures = root.get("closures")
    if not isinstance(raw_closures, list) or not raw_closures:
        raise GapReconciliationError("calendar.closures: expected a non-empty list")
    closures: list[ClosureEvent] = []
    closure_dates: set[date] = set()
    previous_date: date | None = None
    for index, item in enumerate(raw_closures):
        location = f"calendar.closures[{index}]"
        closure = _mapping(item, location)
        _exact_keys(closure, {"date", "name", "source_ids"}, location)
        closure_text = _string(closure, "date", location)
        closure_date = _parse_date(closure_text, f"{location}.date")
        if not start_date <= closure_date < end_date:
            raise GapReconciliationError(f"{location}.date: outside calendar coverage")
        if closure_date in closure_dates:
            raise GapReconciliationError(f"{location}.date: duplicate {closure_text}")
        if previous_date is not None and closure_date <= previous_date:
            raise GapReconciliationError(
                f"{location}.date: closures must be strictly chronological"
            )
        raw_source_ids = closure.get("source_ids")
        if (
            not isinstance(raw_source_ids, list)
            or not raw_source_ids
            or any(not isinstance(value, str) for value in raw_source_ids)
        ):
            raise GapReconciliationError(
                f"{location}.source_ids: expected a non-empty string list"
            )
        event_source_ids = tuple(raw_source_ids)
        if len(set(event_source_ids)) != len(event_source_ids):
            raise GapReconciliationError(
                f"{location}.source_ids: duplicate source identifier"
            )
        unknown_sources = set(event_source_ids) - source_ids
        if unknown_sources:
            raise GapReconciliationError(
                f"{location}.source_ids: unknown sources {sorted(unknown_sources)}"
            )
        closure_dates.add(closure_date)
        previous_date = closure_date
        closures.append(
            ClosureEvent(
                date=closure_text,
                name=_string(closure, "name", location),
                source_ids=event_source_ids,
            )
        )

    return ClosureCalendar(
        schema=schema,
        symbol=symbol,
        timezone=timezone,
        coverage_start_date=coverage_start,
        coverage_end_date_exclusive=coverage_end,
        sources=tuple(sources),
        closures=tuple(closures),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def _window_dates(
    start: datetime,
    end: datetime,
    *,
    window_start: time,
    window_end: time,
    timezone: ZoneInfo,
) -> tuple[str, ...]:
    if start >= end:
        return ()
    first_date = start.astimezone(timezone).date()
    final_date = end.astimezone(timezone).date()
    matched: list[str] = []
    current = first_date
    while current <= final_date:
        if current.weekday() < 5:
            local_start = datetime.combine(current, window_start, tzinfo=timezone)
            local_end = datetime.combine(current, window_end, tzinfo=timezone)
            if start < local_end.astimezone(UTC) and end > local_start.astimezone(UTC):
                matched.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(matched)


def _matching_closures(
    start: datetime,
    end: datetime,
    closures: tuple[ClosureEvent, ...],
    timezone: ZoneInfo,
) -> tuple[ClosureEvent, ...]:
    matched: list[ClosureEvent] = []
    for closure in closures:
        closure_date = date.fromisoformat(closure.date)
        local_start = datetime.combine(closure_date, time.min, tzinfo=timezone)
        local_end = datetime.combine(
            closure_date + timedelta(days=1), time.min, tzinfo=timezone
        )
        if start < local_end.astimezone(UTC) and end > local_start.astimezone(UTC):
            matched.append(closure)
    return tuple(matched)


def _next_research_date(
    value: datetime,
    *,
    timezone: ZoneInfo,
    closure_dates: set[date],
) -> str:
    local = value.astimezone(timezone)
    candidate = local.date()
    if local.time() >= OPERATING_END:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in closure_dates:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _reconcile_gap(
    gap: GapAudit,
    *,
    timeframe: str,
    timeframe_seconds: int,
    calendar: ClosureCalendar,
    timezone: ZoneInfo,
    closure_dates: set[date],
) -> ReconciledGap:
    missing_start_epoch = gap.after_time_epoch + timeframe_seconds
    missing_start = datetime.fromtimestamp(missing_start_epoch, tz=UTC)
    missing_end = datetime.fromtimestamp(gap.before_time_epoch, tz=UTC)
    matched = _matching_closures(
        missing_start, missing_end, calendar.closures, timezone
    )
    operating_dates = _window_dates(
        missing_start,
        missing_end,
        window_start=OPERATING_START,
        window_end=OPERATING_END,
        timezone=timezone,
    )
    candidate_dates = _window_dates(
        missing_start,
        missing_end,
        window_start=CANDIDATE_START,
        window_end=CANDIDATE_END,
        timezone=timezone,
    )

    quarantine_dates: tuple[str, ...] = ()
    if matched:
        resolution = "calendar_correlated_closure"
    elif operating_dates:
        resolution = "quarantined_in_session_gap"
        quarantine_dates = operating_dates
    else:
        resolution = "quarantined_out_of_session_gap"
        if timeframe in {"M15", "H1"}:
            quarantine_dates = (
                _next_research_date(
                    missing_end,
                    timezone=timezone,
                    closure_dates=closure_dates,
                ),
            )

    return ReconciledGap(
        timeframe=timeframe,
        source_month=gap.source_month,
        resolution=resolution,
        matched_closures=tuple(
            f"{closure.date} — {closure.name}" for closure in matched
        ),
        after_time_epoch=gap.after_time_epoch,
        after_time_utc=gap.after_time_utc,
        before_time_epoch=gap.before_time_epoch,
        before_time_utc=gap.before_time_utc,
        missing_start_epoch=missing_start_epoch,
        missing_start_utc=missing_start.isoformat(),
        missing_periods=gap.missing_periods,
        operating_window_overlap=bool(operating_dates),
        candidate_window_overlap=bool(candidate_dates),
        affected_new_york_dates=operating_dates,
        quarantine_session_dates=quarantine_dates,
    )


def reconcile_backfill_gaps(
    audit: BackfillAudit,
    calendar: ClosureCalendar,
) -> GapReconciliation:
    """Classify review gaps and produce explicit no-research session dates."""

    if audit.symbol != calendar.symbol:
        raise GapReconciliationError(
            f"calendar symbol {calendar.symbol!r} does not match {audit.symbol!r}"
        )
    audit_start = date.fromisoformat(f"{audit.start_month}-01")
    audit_end = date.fromisoformat(f"{audit.end_month_exclusive}-01")
    calendar_start = date.fromisoformat(calendar.coverage_start_date)
    calendar_end = date.fromisoformat(calendar.coverage_end_date_exclusive)
    if calendar_start > audit_start or calendar_end < audit_end:
        raise GapReconciliationError(
            "closure calendar does not cover the complete backfill range"
        )

    timezone = ZoneInfo(calendar.timezone)
    closure_dates = {date.fromisoformat(item.date) for item in calendar.closures}
    coverage: dict[str, TimeframeReconciliation] = {}
    observed_abnormal_dates: set[str] = set()
    quarantine_dates: set[str] = set()

    for timeframe, timeframe_seconds in EXPECTED_TIMEFRAMES.items():
        reconciled = tuple(
            _reconcile_gap(
                gap,
                timeframe=timeframe,
                timeframe_seconds=timeframe_seconds,
                calendar=calendar,
                timezone=timezone,
                closure_dates=closure_dates,
            )
            for gap in audit.coverage[timeframe].review_required_gaps
        )
        for gap in reconciled:
            if gap.resolution == "calendar_correlated_closure":
                observed_abnormal_dates.update(gap.affected_new_york_dates)
            quarantine_dates.update(gap.quarantine_session_dates)
        coverage[timeframe] = TimeframeReconciliation(
            timeframe=timeframe,
            review_gap_count=len(reconciled),
            calendar_correlated_count=sum(
                gap.resolution == "calendar_correlated_closure" for gap in reconciled
            ),
            quarantined_in_session_count=sum(
                gap.resolution == "quarantined_in_session_gap" for gap in reconciled
            ),
            quarantined_out_of_session_count=sum(
                gap.resolution == "quarantined_out_of_session_gap" for gap in reconciled
            ),
            gaps=reconciled,
        )

    observed_abnormal_dates = {
        value
        for value in observed_abnormal_dates
        if audit_start <= date.fromisoformat(value) < audit_end
    }
    quarantine_dates = {
        value
        for value in quarantine_dates
        if audit_start <= date.fromisoformat(value) < audit_end
    }
    calendar_exclusions = {
        item.date
        for item in calendar.closures
        if audit_start <= date.fromisoformat(item.date) < audit_end
    }
    excluded = calendar_exclusions | observed_abnormal_dates | quarantine_dates
    quarantined_gap_count = sum(
        item.quarantined_in_session_count + item.quarantined_out_of_session_count
        for item in coverage.values()
    )
    return GapReconciliation(
        schema=REPORT_SCHEMA,
        status=("quarantine_required" if quarantined_gap_count else "reconciled"),
        symbol=audit.symbol,
        server=audit.server,
        backfill_schema=audit.schema,
        backfill_status=audit.status,
        start_month=audit.start_month,
        end_month_exclusive=audit.end_month_exclusive,
        calendar_schema=calendar.schema,
        calendar_sha256=calendar.sha256,
        calendar_sources=calendar.sources,
        calendar_exclusion_dates=tuple(sorted(calendar_exclusions)),
        observed_abnormal_session_dates=tuple(sorted(observed_abnormal_dates)),
        quarantine_session_dates=tuple(sorted(quarantine_dates)),
        excluded_session_dates=tuple(sorted(excluded)),
        coverage=coverage,
    )


def write_reconciliation(report: GapReconciliation, output: Path) -> None:
    """Write a reconciliation receipt atomically."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile Sika MT5 gaps with a versioned closure calendar."
    )
    parser.add_argument("root", type=Path, help="MT5 Sika/backfill directory")
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--start-month", default=DEFAULT_START_MONTH)
    parser.add_argument("--end-month-exclusive", default=DEFAULT_END_MONTH_EXCLUSIVE)
    parser.add_argument("--expected-symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        logger = command_logger("mt5_reconcile_gaps")
    except (ConfigurationError, OSError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return 2

    logger.info("gap reconciliation started", extra={"event": "reconciliation_started"})
    try:
        audit = validate_backfill(
            args.root,
            start_month=args.start_month,
            end_month_exclusive=args.end_month_exclusive,
            expected_symbol=args.expected_symbol,
        )
        calendar = load_closure_calendar(args.calendar)
        report = reconcile_backfill_gaps(audit, calendar)
        write_reconciliation(report, args.output)
    except (BackfillValidationError, GapReconciliationError, OSError) as exc:
        logger.error(
            "gap reconciliation failed: %s",
            exc,
            extra={"event": "reconciliation_failed"},
        )
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"{report.status.upper()} {report.symbol}: "
            f"excluded_sessions={len(report.excluded_session_dates)}, "
            f"quarantine_sessions={len(report.quarantine_session_dates)}"
        )
        for timeframe in EXPECTED_TIMEFRAMES:
            item = report.coverage[timeframe]
            print(
                f"{timeframe}: review_gaps={item.review_gap_count}, "
                f"calendar_correlated={item.calendar_correlated_count}, "
                f"quarantined_in_session={item.quarantined_in_session_count}, "
                f"quarantined_out_of_session="
                f"{item.quarantined_out_of_session_count}"
            )
    if report.status == "quarantine_required":
        logger.warning(
            "gap reconciliation completed with status quarantine_required",
            extra={"event": "reconciliation_completed"},
        )
        print(
            "QUARANTINE REQUIRED: downstream research must exclude every listed "
            "session before this dataset can pass the data-quality gate.",
            file=sys.stderr,
        )
        return 4
    logger.info(
        "gap reconciliation completed with status reconciled",
        extra={"event": "reconciliation_completed"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
