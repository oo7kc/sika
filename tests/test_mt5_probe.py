from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from sika.market_data.mt5_probe import ProbeError, run_probe


NOW = datetime(2026, 10, 2, 16, 7, tzinfo=UTC)


def make_bars(*, seconds: int, count: int = 12) -> list[dict[str, float | int]]:
    latest_open = int(NOW.timestamp()) - 7 * 60
    return [
        {
            "time": latest_open - seconds * (count - index - 1),
            "open": 3800.0 + index,
            "high": 3801.0 + index,
            "low": 3799.0 + index,
            "close": 3800.5 + index,
            "tick_volume": 100 + index,
            "spread": 20,
            "real_volume": 0,
        }
        for index in range(count)
    ]


class FakeMT5:
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self) -> None:
        self.shutdown_called = False
        self.initialize_result = True
        self.connected = True
        self.account_server = "Exness-MT5Trial"
        self.account_company = "Exness"
        self.trade_mode = 0
        self.rates = {
            self.TIMEFRAME_M15: make_bars(seconds=15 * 60),
            self.TIMEFRAME_H1: make_bars(seconds=60 * 60),
        }

    def initialize(self, *args: str) -> bool:
        self.initialize_args = args
        return self.initialize_result

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> tuple[int, str]:
        return (-1, "fixture error")

    def version(self) -> tuple[int, int, str]:
        return (500, 6231, "27 Sep 2026")

    def terminal_info(self) -> SimpleNamespace:
        return SimpleNamespace(
            connected=self.connected,
            trade_allowed=False,
            tradeapi_disabled=True,
            name="MetaTrader 5",
            company="Exness",
            build=6231,
            maxbars=100000,
        )

    def account_info(self) -> SimpleNamespace:
        return SimpleNamespace(
            login=123456,
            name="Must Not Leak",
            balance=12345.67,
            server=self.account_server,
            company=self.account_company,
            currency="USD",
            trade_mode=self.trade_mode,
            margin_mode=2,
        )

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        return symbol == "XAUUSDm" and enable

    def symbol_info(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(
            name=symbol,
            description="Gold vs US Dollar",
            path="Forex\\XAUUSDm",
            currency_base="XAU",
            currency_profit="USD",
            currency_margin="XAU",
            digits=3,
            point=0.001,
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=200.0,
            spread=200,
            spread_float=True,
            trade_stops_level=0,
            trade_freeze_level=0,
            trade_mode=4,
            filling_mode=3,
        )

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(
            time=int(NOW.timestamp()) - 1,
            time_msc=(int(NOW.timestamp()) - 1) * 1000,
            bid=3800.0,
            ask=3800.2,
            last=0.0,
            flags=6,
        )

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict[str, float | int]]:
        return self.rates[timeframe][-count:]


class MT5ProbeTests(unittest.TestCase):
    def test_probe_is_redacted_and_excludes_forming_bars(self) -> None:
        api = FakeMT5()

        report = run_probe(api, symbol="XAUUSDm", bar_count=10, now=NOW)

        self.assertEqual(report["mode"], "read-only")
        self.assertEqual(report["symbol"], "XAUUSDm")
        self.assertEqual(report["account"]["server"], "Exness-MT5Trial")
        self.assertNotIn("login", report["account"])
        self.assertNotIn("name", report["account"])
        self.assertNotIn("balance", report["account"])
        self.assertEqual(report["account"]["profile"], "Standard")
        self.assertEqual(report["account"]["profile_source"], "research-contract-v0.1")
        self.assertEqual(report["bars"]["M15"]["completed_bars"], 10)
        self.assertEqual(report["bars"]["H1"]["completed_bars"], 10)
        self.assertEqual(report["bars"]["M15"]["forming_bars_excluded"], 1)
        self.assertGreaterEqual(report["bars"]["H1"]["forming_bars_excluded"], 1)
        self.assertTrue(api.shutdown_called)

    def test_closed_market_surplus_is_not_reported_as_a_forming_bar(self) -> None:
        api = FakeMT5()
        api.rates[api.TIMEFRAME_M15][-1]["time"] = int(NOW.timestamp()) - 20 * 60

        report = run_probe(api, symbol="XAUUSDm", bar_count=10, now=NOW)

        self.assertEqual(report["bars"]["M15"]["forming_bars_excluded"], 0)
        self.assertEqual(
            report["bars"]["M15"]["surplus_completed_bars_excluded"], 1
        )

    def test_shutdown_runs_when_bar_validation_fails(self) -> None:
        api = FakeMT5()
        api.rates[api.TIMEFRAME_M15][-2]["low"] = 9999.0

        with self.assertRaisesRegex(ProbeError, "Bar low"):
            run_probe(api, symbol="XAUUSDm", bar_count=10, now=NOW)

        self.assertTrue(api.shutdown_called)

    def test_initialization_failure_is_reported_without_shutdown(self) -> None:
        api = FakeMT5()
        api.initialize_result = False

        with self.assertRaisesRegex(ProbeError, "Could not initialize"):
            run_probe(api, symbol="XAUUSDm", bar_count=10, now=NOW)

        self.assertFalse(api.shutdown_called)

    def test_rejects_wrong_symbol_before_using_market_data(self) -> None:
        api = FakeMT5()

        with self.assertRaisesRegex(ProbeError, "requires symbol 'XAUUSDm'"):
            run_probe(api, symbol="XAUUSD247", bar_count=10, now=NOW)

        self.assertFalse(api.shutdown_called)

    def test_rejects_untrusted_terminal_or_account_context(self) -> None:
        cases = (
            ("disconnected", {"connected": False}, "not connected"),
            (
                "wrong server",
                {"account_server": "Other-Live"},
                "Expected an Exness server",
            ),
            (
                "wrong company",
                {"account_company": "Other Broker"},
                "Expected an Exness account company",
            ),
            ("live account", {"trade_mode": 2}, "demo accounts only"),
        )

        for label, overrides, message in cases:
            with self.subTest(label=label):
                api = FakeMT5()
                for name, value in overrides.items():
                    setattr(api, name, value)
                with self.assertRaisesRegex(ProbeError, message):
                    run_probe(api, symbol="XAUUSDm", bar_count=10, now=NOW)
                self.assertTrue(api.shutdown_called)

    def test_rejects_an_underfilled_history_request(self) -> None:
        api = FakeMT5()
        api.rates[api.TIMEFRAME_M15] = make_bars(seconds=15 * 60, count=3)

        with self.assertRaisesRegex(
            ProbeError, "returned 2 completed M15 bars; exactly 10 were requested"
        ):
            run_probe(api, symbol="XAUUSDm", bar_count=10, now=NOW)

        self.assertTrue(api.shutdown_called)


if __name__ == "__main__":
    unittest.main()
