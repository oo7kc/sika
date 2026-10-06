"""Read-only health and data-quality probe for a locally running MT5 terminal.

The module deliberately exposes no order-management methods and accepts no account
credentials. It attaches to the account already signed into the local terminal.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


EXPECTED_SYMBOL = "XAUUSDm"
EXPECTED_ACCOUNT_PROFILE = "Standard"
DEMO_TRADE_MODE = 0


class ProbeError(RuntimeError):
    """Raised when MT5 cannot provide a trustworthy probe result."""


class MT5Api(Protocol):
    """Narrow, read-only subset of the MetaTrader5 module used by this probe."""

    TIMEFRAME_M15: int
    TIMEFRAME_H1: int

    def initialize(self, *args: str) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> object: ...

    def version(self) -> object: ...

    def terminal_info(self) -> object: ...

    def account_info(self) -> object: ...

    def symbol_select(self, symbol: str, enable: bool) -> bool: ...

    def symbol_info(self, symbol: str) -> object: ...

    def symbol_info_tick(self, symbol: str) -> object: ...

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> object: ...


@dataclass(frozen=True)
class Timeframe:
    name: str
    api_attribute: str
    seconds: int


TIMEFRAMES = (
    Timeframe("M15", "TIMEFRAME_M15", 15 * 60),
    Timeframe("H1", "TIMEFRAME_H1", 60 * 60),
)


def load_mt5_api() -> MT5Api:
    """Load MetaQuotes' terminal bridge only when a real probe is requested."""

    try:
        module = importlib.import_module("MetaTrader5")
    except ModuleNotFoundError as exc:
        raise ProbeError(
            "MetaTrader5 is not installed. Run this command on 64-bit Windows "
            "beside the signed-in MT5 terminal after installing the project "
            "dependencies. MetaQuotes does not publish Linux wheels."
        ) from exc
    return module  # type: ignore[return-value]


def _value(record: object, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    try:
        return record[name]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return getattr(record, name, default)


def _safe_fields(record: object, names: Sequence[str]) -> dict[str, Any]:
    return {name: _value(record, name) for name in names}


def _iso_utc(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).isoformat()


def _last_error(api: MT5Api) -> str:
    try:
        return repr(api.last_error())
    except Exception:
        return "unavailable"


def _terminal_summary(api: MT5Api) -> dict[str, Any]:
    terminal = api.terminal_info()
    if terminal is None:
        raise ProbeError(f"MT5 returned no terminal information: {_last_error(api)}")
    return _safe_fields(
        terminal,
        (
            "connected",
            "trade_allowed",
            "tradeapi_disabled",
            "name",
            "company",
            "build",
            "maxbars",
        ),
    )


def _account_summary(api: MT5Api) -> dict[str, Any]:
    account = api.account_info()
    if account is None:
        raise ProbeError(f"MT5 returned no account information: {_last_error(api)}")
    # Login, holder name, balance, equity and margin are intentionally excluded.
    return _safe_fields(
        account,
        ("server", "company", "currency", "trade_mode", "margin_mode"),
    )


def _validate_environment(
    terminal: Mapping[str, Any], account: Mapping[str, Any]
) -> None:
    if terminal.get("connected") is not True:
        raise ProbeError("MT5 is not connected to a trade server")

    server = account.get("server")
    company = account.get("company")
    if not isinstance(server, str) or not server.startswith("Exness-"):
        raise ProbeError(f"Expected an Exness server, received {server!r}")
    if not isinstance(company, str) or "Exness" not in company:
        raise ProbeError(f"Expected an Exness account company, received {company!r}")
    if account.get("trade_mode") != DEMO_TRADE_MODE:
        raise ProbeError("The v0 research boundary permits demo accounts only")


def _symbol_summary(api: MT5Api, symbol: str) -> tuple[dict[str, Any], float]:
    if not api.symbol_select(symbol, True):
        raise ProbeError(
            f"MT5 could not enable {symbol!r} in Market Watch: {_last_error(api)}"
        )

    info = api.symbol_info(symbol)
    if info is None:
        raise ProbeError(f"MT5 returned no specification for {symbol!r}")

    point = float(_value(info, "point", 0.0))
    if not math.isfinite(point) or point <= 0:
        raise ProbeError(f"{symbol!r} has an invalid point size: {point!r}")

    fields = _safe_fields(
        info,
        (
            "name",
            "description",
            "path",
            "currency_base",
            "currency_profit",
            "currency_margin",
            "digits",
            "point",
            "trade_contract_size",
            "volume_min",
            "volume_step",
            "volume_max",
            "spread",
            "spread_float",
            "trade_stops_level",
            "trade_freeze_level",
            "trade_mode",
            "filling_mode",
        ),
    )
    return fields, point


def _tick_summary(
    api: MT5Api,
    symbol: str,
    point: float,
    now: datetime,
    stale_after_seconds: int,
) -> dict[str, Any]:
    tick = api.symbol_info_tick(symbol)
    if tick is None:
        raise ProbeError(f"MT5 returned no latest tick for {symbol!r}: {_last_error(api)}")

    bid = float(_value(tick, "bid", 0.0))
    ask = float(_value(tick, "ask", 0.0))
    if not all(math.isfinite(value) and value > 0 for value in (bid, ask)):
        raise ProbeError(f"{symbol!r} returned a non-positive or non-finite bid/ask")
    if ask < bid:
        raise ProbeError(f"{symbol!r} returned ask below bid: bid={bid}, ask={ask}")

    time_msc = int(_value(tick, "time_msc", 0) or 0)
    epoch = time_msc / 1000 if time_msc else float(_value(tick, "time", 0))
    if epoch <= 0:
        raise ProbeError(f"{symbol!r} returned an invalid tick timestamp")

    age_seconds = (now.timestamp() - epoch)
    return {
        "time_utc": _iso_utc(epoch),
        "age_seconds": round(age_seconds, 3),
        "stale": age_seconds > stale_after_seconds,
        "bid": bid,
        "ask": ask,
        "last": float(_value(tick, "last", 0.0)),
        "spread_price": ask - bid,
        "spread_points": (ask - bid) / point,
        "flags": int(_value(tick, "flags", 0)),
    }


def _normalise_bar(row: object) -> dict[str, float | int]:
    bar = {
        "time": int(_value(row, "time", 0)),
        "open": float(_value(row, "open", math.nan)),
        "high": float(_value(row, "high", math.nan)),
        "low": float(_value(row, "low", math.nan)),
        "close": float(_value(row, "close", math.nan)),
        "tick_volume": int(_value(row, "tick_volume", 0)),
        "spread": int(_value(row, "spread", 0)),
        "real_volume": int(_value(row, "real_volume", 0)),
    }
    prices = (bar["open"], bar["high"], bar["low"], bar["close"])
    if bar["time"] <= 0 or not all(
        isinstance(value, float) and math.isfinite(value) and value > 0
        for value in prices
    ):
        raise ProbeError(f"Invalid bar values returned by MT5: {bar!r}")
    if bar["low"] > min(bar["open"], bar["close"]):
        raise ProbeError(f"Bar low exceeds its open/close: {bar!r}")
    if bar["high"] < max(bar["open"], bar["close"]):
        raise ProbeError(f"Bar high is below its open/close: {bar!r}")
    if bar["high"] < bar["low"]:
        raise ProbeError(f"Bar high is below its low: {bar!r}")
    if bar["tick_volume"] < 0 or bar["real_volume"] < 0 or bar["spread"] < 0:
        raise ProbeError(f"Bar has a negative volume or spread: {bar!r}")
    return bar


def _bar_summary(
    api: MT5Api,
    symbol: str,
    timeframe: Timeframe,
    count: int,
    now: datetime,
) -> dict[str, Any]:
    api_timeframe = getattr(api, timeframe.api_attribute)
    raw = api.copy_rates_from_pos(symbol, api_timeframe, 0, count + 1)
    if raw is None:
        raise ProbeError(
            f"MT5 returned no {timeframe.name} bars for {symbol!r}: {_last_error(api)}"
        )

    rows = [_normalise_bar(row) for row in raw]  # type: ignore[union-attr]
    if not rows:
        raise ProbeError(f"MT5 returned an empty {timeframe.name} series for {symbol!r}")

    timestamps = [int(row["time"]) for row in rows]
    if timestamps != sorted(timestamps):
        raise ProbeError(f"{timeframe.name} bar timestamps are not monotonic")
    if len(set(timestamps)) != len(timestamps):
        raise ProbeError(f"{timeframe.name} bar timestamps contain duplicates")

    cutoff = now.timestamp()
    all_completed = [
        row for row in rows if int(row["time"]) + timeframe.seconds <= cutoff
    ]
    completed = all_completed[-count:]
    if len(completed) != count:
        raise ProbeError(
            f"MT5 returned {len(completed)} completed {timeframe.name} bars; "
            f"exactly {count} were requested"
        )

    completed_times = [int(row["time"]) for row in completed]
    irregular = []
    for previous, current in zip(completed_times, completed_times[1:]):
        delta = current - previous
        if delta != timeframe.seconds:
            irregular.append(
                {
                    "after_utc": _iso_utc(previous),
                    "before_utc": _iso_utc(current),
                    "interval_seconds": delta,
                }
            )

    return {
        "requested_completed_bars": count,
        "returned_raw_bars": len(rows),
        "completed_bars": len(completed),
        "forming_bars_excluded": len(rows) - len(all_completed),
        "surplus_completed_bars_excluded": len(all_completed) - len(completed),
        "first_open_utc": _iso_utc(completed_times[0]),
        "last_open_utc": _iso_utc(completed_times[-1]),
        "last_close": completed[-1]["close"],
        "irregular_interval_count": len(irregular),
        "irregular_interval_samples": irregular[:5],
    }


def run_probe(
    api: MT5Api,
    *,
    symbol: str,
    bar_count: int = 500,
    terminal_path: Path | None = None,
    stale_after_seconds: int = 120,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach to MT5 and return a redacted, read-only data-quality report."""

    if symbol != EXPECTED_SYMBOL:
        raise ProbeError(
            f"The v0 research boundary requires symbol {EXPECTED_SYMBOL!r}; "
            f"received {symbol!r}"
        )
    if bar_count < 10:
        raise ProbeError("bar_count must be at least 10")
    if stale_after_seconds <= 0:
        raise ProbeError("stale_after_seconds must be positive")

    now = now or datetime.now(tz=UTC)
    if now.tzinfo is None:
        raise ProbeError("now must be timezone-aware")
    now = now.astimezone(UTC)

    args = (str(terminal_path),) if terminal_path else ()
    if not api.initialize(*args):
        raise ProbeError(f"Could not initialize the MT5 terminal: {_last_error(api)}")

    try:
        terminal = _terminal_summary(api)
        account = _account_summary(api)
        _validate_environment(terminal, account)
        account["profile"] = EXPECTED_ACCOUNT_PROFILE
        account["profile_source"] = "research-contract-v0.1"
        specification, point = _symbol_summary(api, symbol)
        tick = _tick_summary(api, symbol, point, now, stale_after_seconds)
        bars = {
            timeframe.name: _bar_summary(api, symbol, timeframe, bar_count, now)
            for timeframe in TIMEFRAMES
        }

        warnings: list[str] = []
        if tick["stale"]:
            warnings.append(
                "Latest tick is stale. This is expected while the market is closed; "
                "otherwise verify the terminal connection."
            )
        if terminal.get("trade_allowed"):
            warnings.append(
                "Terminal AutoTrading is enabled. This probe has no order code, but "
                "disable AutoTrading during data-only setup."
            )
        if terminal.get("tradeapi_disabled"):
            warnings.append(
                "External Python trading is disabled in MT5; this does not block the "
                "read-only data probe."
            )

        return {
            "schema_version": "mt5-probe-v2",
            "contract_version": "v0.1",
            "mode": "read-only",
            "generated_at_utc": now.isoformat(),
            "symbol": symbol,
            "mt5_package_version": list(api.version()),  # type: ignore[arg-type]
            "terminal": terminal,
            "account": account,
            "specification": specification,
            "tick": tick,
            "bars": bars,
            "warnings": warnings,
        }
    finally:
        api.shutdown()


def write_report(report: Mapping[str, Any], output: Path) -> None:
    """Write a report atomically so interrupted probes cannot leave partial JSON."""

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a read-only MT5 connection and market-data probe."
    )
    parser.add_argument("--symbol", default="XAUUSDm", help="Exact MT5 symbol name")
    parser.add_argument(
        "--bars", type=int, default=500, help="Completed bars to inspect per timeframe"
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=120,
        help="Age at which the latest tick is reported as stale",
    )
    parser.add_argument(
        "--terminal-path",
        type=Path,
        help="Optional path to terminal64.exe; auto-discovered when omitted",
    )
    parser.add_argument(
        "--output", type=Path, help="Optional JSON report path; stdout is always used"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_probe(
            load_mt5_api(),
            symbol=args.symbol,
            bar_count=args.bars,
            terminal_path=args.terminal_path,
            stale_after_seconds=args.stale_after_seconds,
        )
        if args.output:
            write_report(report, args.output)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except ProbeError as exc:
        print(f"MT5 probe failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
