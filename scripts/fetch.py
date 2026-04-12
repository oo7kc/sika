"""Tiingo market data client — historical fetch, current price, and local sync."""

from datetime import date
from pathlib import Path

import pandas as pd
import requests

from config import Config
from scripts.data import is_crypto
from scripts.logger import get_logger

logger = get_logger(__name__)

_CRYPTO_URL = "https://api.tiingo.com/tiingo/crypto/prices"
_FX_URL = "https://api.tiingo.com/tiingo/fx/{ticker}/prices"


class MarketDataPipeline:
    """Fetch OHLCV data from Tiingo and sync to local CSV."""

    def __init__(self, pair: str) -> None:
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.api_key = self.config.TIINGO_KEY
        if not self.api_key:
            raise ValueError("TIINGO_KEY is not set. Add it to your .env file.")

    def _get(self, url: str, **params: str) -> dict | list:
        """GET request to Tiingo with token authentication."""
        params["token"] = self.api_key
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(
                f"Tiingo HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Tiingo request failed: {e}") from e

    def _extract_bars(self, payload: object) -> list[dict]:
        """Normalize Tiingo payload into flat list of bar dicts."""
        if not payload:
            return []
        if isinstance(payload, list):
            first = payload[0] if payload else {}
            return payload if "date" in first else first.get("priceData", [])
        if isinstance(payload, dict):
            return payload.get("priceData", [])
        return []

    def _bars_to_df(self, bars: list[dict], label: str) -> pd.DataFrame:
        """Parse raw bars into clean OHLCV DataFrame."""
        rows = []
        for item in bars:
            try:
                rows.append(
                    {
                        "Date": item["date"],
                        "Open": float(item.get("open") or item.get("close") or 0),
                        "High": float(item.get("high") or 0),
                        "Low": float(item.get("low") or 0),
                        "Close": float(item.get("close") or 0),
                        "Volume": float(item.get("volume") or 0),
                    }
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed bar for {label}: {e}")

        if not rows:
            raise RuntimeError(f"No valid bars parsed for {label}")

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        return df.set_index("Date").sort_index()

    def fetch_history(self) -> pd.DataFrame:
        """Fetch full historical OHLCV from Tiingo."""
        logger.info(f"Fetching history for {self.pair}")
        if is_crypto(self.pair):
            return self._fetch_crypto_history()
        return self._fetch_fx_history()

    def _fetch_crypto_history(self) -> pd.DataFrame:
        payload = self._get(
            _CRYPTO_URL,
            tickers=self.pair.lower(),
            startDate=self.config.START_DATE,
            resampleFreq="1Day",
        )
        bars = self._extract_bars(payload)
        if not bars:
            raise RuntimeError(f"No crypto history returned for {self.pair}")
        df = self._bars_to_df(bars, self.pair)
        logger.info(f"Fetched {len(df)} crypto bars for {self.pair}")
        return df

    def _fetch_fx_history(self) -> pd.DataFrame:
        url = _FX_URL.format(ticker=self.pair.lower())
        payload = self._get(url, startDate=self.config.START_DATE, resampleFreq="1Day")
        bars = self._extract_bars(payload)
        if not bars:
            raise RuntimeError(f"No FX history returned for {self.pair}")
        df = self._bars_to_df(bars, self.pair)
        logger.info(f"Fetched {len(df)} FX bars for {self.pair}")
        return df

    def fetch_current_price(self) -> float:
        """Fetch most recent price from 1-min bar close."""
        logger.info(f"Fetching current price for {self.pair}")
        url = (
            _CRYPTO_URL
            if is_crypto(self.pair)
            else _FX_URL.format(ticker=self.pair.lower())
        )
        params: dict[str, str] = {"resampleFreq": "1Min"}
        if not is_crypto(self.pair):
            params["startDate"] = self.config.START_DATE
        else:
            params["tickers"] = self.pair.lower()

        payload = self._get(url, **params)
        bars = self._extract_bars(payload)
        if not bars:
            raise RuntimeError(f"No current price data returned for {self.pair}")

        latest = bars[-1]
        price = float(latest.get("close") or latest.get("open") or 0)
        logger.info(f"Current price for {self.pair}: {price}")
        return price

    def fetch_open_for_date(self, prediction_date: date) -> float:
        """Return open price for date, current price for today."""
        if prediction_date == date.today():
            return self.fetch_current_price()

        history = self.fetch_history()
        ts = pd.Timestamp(prediction_date)
        if ts in history.index:
            return float(history.loc[ts, "Open"])

        logger.warning(f"{prediction_date} not in history — using most recent bar")
        return float(history.iloc[-1]["Open"])

    def fetch_actuals_for_date(self, prediction_date: date) -> dict | None:
        """Return completed OHLCV bar for past date, or None if unavailable."""
        history = self.fetch_history()
        ts = pd.Timestamp(prediction_date)
        if ts not in history.index:
            logger.warning(f"Actual data not available for {prediction_date}")
            return None
        row = history.loc[ts]
        return {
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        }

    def sync_raw_data(self) -> Path:
        """Fetch history and merge with local raw CSV, deduplicating by date."""
        history = self.fetch_history()
        history.index = pd.to_datetime(history.index)
        history.index.name = "Date"

        path = Path(self.paths["raw_data"])
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            try:
                existing = pd.read_csv(path, index_col=0)
                existing.index = pd.to_datetime(existing.index, format="mixed")
                data = pd.concat([existing, history])
                data = data[~data.index.duplicated(keep="last")].sort_index()
                msg = (
                    f"Merged {len(existing)} existing + {len(history)} "
                    f"fetched rows → {len(data)} total"
                )
                logger.info(msg)
            except Exception as e:
                msg = f"Could not merge existing data — overwriting: {e}"
                logger.error(msg)
                data = history
        else:
            data = history

        try:
            data.to_csv(path)
            logger.info(f"Raw data synced → {path}")
            return path
        except Exception as e:
            raise RuntimeError(f"Could not write raw data: {e}") from e
