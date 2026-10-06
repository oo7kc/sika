from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sika.market_data.mt5_backfill import (
    BackfillAudit,
    GapAudit,
    TimeframeCoverage,
)
from sika.market_data.mt5_gap_reconciliation import (
    CALENDAR_SCHEMA,
    GapReconciliationError,
    load_closure_calendar,
    reconcile_backfill_gaps,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CALENDAR = (
    REPOSITORY_ROOT / "config" / "market_data" / "xauusdm-closures-v1.json"
)


def epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def gap(
    after: str,
    before: str,
    *,
    timeframe_seconds: int,
    source_month: str = "2022-01",
) -> GapAudit:
    after_epoch = epoch(after)
    before_epoch = epoch(before)
    return GapAudit(
        source_month=source_month,
        classification="review_required",
        after_time_epoch=after_epoch,
        after_time_utc=datetime.fromtimestamp(after_epoch, UTC).isoformat(),
        before_time_epoch=before_epoch,
        before_time_utc=datetime.fromtimestamp(before_epoch, UTC).isoformat(),
        interval_seconds=before_epoch - after_epoch,
        missing_periods=(before_epoch - after_epoch) // timeframe_seconds - 1,
    )


def coverage(timeframe: str, gaps: tuple[GapAudit, ...]) -> TimeframeCoverage:
    return TimeframeCoverage(
        timeframe=timeframe,
        file_count=1,
        bar_count=2,
        first_time_epoch=epoch("2022-01-01T00:00:00"),
        first_time_utc="2022-01-01T00:00:00+00:00",
        last_time_epoch=epoch("2022-01-31T23:00:00"),
        last_time_utc="2022-01-31T23:00:00+00:00",
        weekend_closure_candidate_count=0,
        rollover_closure_candidate_count=0,
        closure_candidate_samples=(),
        review_required_gaps=gaps,
    )


def audit_with(
    *,
    m1: tuple[GapAudit, ...] = (),
    m15: tuple[GapAudit, ...] = (),
    h1: tuple[GapAudit, ...] = (),
) -> BackfillAudit:
    return BackfillAudit(
        schema="sika-mt5-backfill-month-v1",
        status="review_required" if m1 or m15 or h1 else "structurally_valid",
        symbol="XAUUSDm",
        server="Exness-MT5Trial9",
        account_company="Exness Technologies Ltd",
        account_profile="Standard",
        start_month="2022-01",
        end_month_exclusive="2022-02",
        month_count=1,
        bundles=(),
        coverage={
            "M1": coverage("M1", m1),
            "M15": coverage("M15", m15),
            "H1": coverage("H1", h1),
        },
    )


def calendar_payload() -> dict[str, object]:
    return {
        "schema": CALENDAR_SCHEMA,
        "symbol": "XAUUSDm",
        "timezone": "America/New_York",
        "coverage_start_date": "2022-01-01",
        "coverage_end_date_exclusive": "2022-02-01",
        "sources": [
            {
                "id": "official-calendar",
                "title": "Official calendar",
                "url": "https://example.test/calendar",
                "scope": "Test evidence",
            }
        ],
        "closures": [
            {
                "date": "2022-01-17",
                "name": "Martin Luther King Jr. Day",
                "source_ids": ["official-calendar"],
            }
        ],
    }


class MT5GapReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.calendar_path = Path(self.tempdir.name) / "calendar.json"
        self.calendar_path.write_text(json.dumps(calendar_payload()), encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_production_calendar_is_valid_and_has_traceable_sources(self) -> None:
        calendar = load_closure_calendar(PRODUCTION_CALENDAR)

        self.assertEqual(calendar.symbol, "XAUUSDm")
        self.assertEqual(len(calendar.closures), 50)
        self.assertGreaterEqual(len(calendar.sources), 7)
        self.assertEqual(len(calendar.sha256), 64)

    def test_rejects_a_closure_with_an_unknown_source(self) -> None:
        payload = calendar_payload()
        payload["closures"][0]["source_ids"] = ["missing-source"]
        self.calendar_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(GapReconciliationError, "unknown sources"):
            load_closure_calendar(self.calendar_path)

    def test_calendar_correlated_gap_excludes_the_abnormal_session(self) -> None:
        calendar = load_closure_calendar(self.calendar_path)
        holiday_gap = gap(
            "2022-01-17T18:45:00",
            "2022-01-17T23:00:00",
            timeframe_seconds=900,
        )

        report = reconcile_backfill_gaps(audit_with(m15=(holiday_gap,)), calendar)

        item = report.coverage["M15"]
        self.assertEqual(item.calendar_correlated_count, 1)
        self.assertEqual(item.gaps[0].resolution, "calendar_correlated_closure")
        self.assertIn("2022-01-17", report.excluded_session_dates)
        self.assertEqual(report.status, "reconciled")

    def test_unexplained_in_session_gap_is_quarantined(self) -> None:
        calendar = load_closure_calendar(self.calendar_path)
        feed_gap = gap(
            "2022-01-18T14:59:00",
            "2022-01-18T15:02:00",
            timeframe_seconds=60,
        )

        report = reconcile_backfill_gaps(audit_with(m1=(feed_gap,)), calendar)

        item = report.coverage["M1"]
        self.assertEqual(item.quarantined_in_session_count, 1)
        self.assertEqual(report.quarantine_session_dates, ("2022-01-18",))
        self.assertEqual(report.status, "quarantine_required")

    def test_out_of_session_m1_gap_does_not_exclude_a_research_session(self) -> None:
        calendar = load_closure_calendar(self.calendar_path)
        feed_gap = gap(
            "2022-01-18T23:00:00",
            "2022-01-18T23:03:00",
            timeframe_seconds=60,
        )

        report = reconcile_backfill_gaps(audit_with(m1=(feed_gap,)), calendar)

        self.assertEqual(report.coverage["M1"].quarantined_out_of_session_count, 1)
        self.assertEqual(report.quarantine_session_dates, ())

    def test_out_of_session_context_gap_quarantines_the_next_session(self) -> None:
        calendar = load_closure_calendar(self.calendar_path)
        feed_gap = gap(
            "2022-01-18T23:45:00",
            "2022-01-19T01:15:00",
            timeframe_seconds=900,
        )

        report = reconcile_backfill_gaps(audit_with(m15=(feed_gap,)), calendar)

        self.assertEqual(report.quarantine_session_dates, ("2022-01-19",))
        self.assertIn("2022-01-19", report.excluded_session_dates)

    def test_context_quarantine_does_not_escape_the_audited_range(self) -> None:
        calendar = load_closure_calendar(self.calendar_path)
        final_gap = gap(
            "2022-01-31T23:45:00",
            "2022-02-01T01:15:00",
            timeframe_seconds=900,
        )

        report = reconcile_backfill_gaps(audit_with(m15=(final_gap,)), calendar)

        self.assertEqual(report.quarantine_session_dates, ())
        self.assertNotIn("2022-02-01", report.excluded_session_dates)

    def test_calendar_must_cover_the_complete_backfill_range(self) -> None:
        calendar = load_closure_calendar(self.calendar_path)
        audit = replace(audit_with(), start_month="2021-12")

        with self.assertRaisesRegex(GapReconciliationError, "does not cover"):
            reconcile_backfill_gaps(audit, calendar)


if __name__ == "__main__":
    unittest.main()
