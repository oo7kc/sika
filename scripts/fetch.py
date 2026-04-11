"""Tiingo market-data fetch and local raw-data sync."""

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from config import Config
from scripts.logger import get_logger

logger = get_logger(__name__)


class MarketDataPipeline:
    FOREX_BASE_URL = "https://api.tiingo.com/tiingo/fx/historical"
    CRYPTO_BASE_URL = "https://api.tiingo.com/tiingo/crypto/prices"
    FOREX_PRICES_URL = "https://api.tiingo.com/tiingo/fx/prices"

    def __init__(self, pair: str):
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.api_key = self.config.TIINGO_KEY
        if not self.api_key:
            raise ValueError("Missing TIINGO_KEY in environment.")

    def _is_forex(self) -> bool:
        """Determine if pair is forex."""
        return self.pair in ["XAUUSD"]

    def _is_crypto(self) -> bool:
        """Determine if pair is cryptocurrency."""
        return self.pair in ["BTCUSD"]

    def _query(self, url: str, **params) -> dict:
        """Make HTTP request to Tiingo API."""
        full_url = f"{url}?{urlencode({**params, 'token': self.api_key})}"
        logger.info(f"Fetching Tiingo data for {self.pair}")
        try:
            with urlopen(full_url) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to fetch from Tiingo: {e}")
            raise RuntimeError(f"Failed to fetch from Tiingo: {e}") from e

        # Check for Tiingo errors
        if isinstance(payload, dict):
            if "error" in payload:
                raise RuntimeError(f"Tiingo API error: {payload['error']}")
            if "message" in payload:
                raise RuntimeError(f"Tiingo API message: {payload['message']}")

        return payload

    def fetch_history(self) -> pd.DataFrame:
        """Fetch historical OHLCV data from Tiingo."""
        if self._is_forex():
            return self._fetch_forex_history()
        elif self._is_crypto():
            return self._fetch_crypto_history()
        else:
            raise ValueError(f"Unsupported pair: {self.pair}")

    def _fetch_forex_history(self) -> pd.DataFrame:
        """Fetch forex (XAUUSD) historical data."""
        ticker = self.pair.lower()
        payload = self._query(
            self.FOREX_BASE_URL,
            tickers=ticker,
            startDate=self.config.START_DATE,
            resampleFreq="daily",
        )

        # Handle single ticker response
        if isinstance(payload, dict) and "priceData" in payload:
            price_data = payload["priceData"]
        elif isinstance(payload, list) and len(payload) > 0:
            price_data = payload[0].get("priceData", [])
        else:
            raise RuntimeError(f"Unexpected Tiingo response format: {payload}")

        rows = []
        for item in price_data:
            rows.append(
                {
                    "Date": item["date"],
                    "Open": float(item.get("open", item.get("close", 0))),
                    "High": float(item["high"]),
                    "Low": float(item["low"]),
                    "Close": float(item["close"]),
                    "Volume": float(item.get("volume", 0)),
                }
            )

        if not rows:
            raise RuntimeError(f"No price data returned for {self.pair}")

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        logger.info(f"Fetched {len(df)} rows for {self.pair}")
        return df

    def _fetch_crypto_history(self) -> pd.DataFrame:
        """Fetch crypto (BTCUSD) historical data."""
        ticker = self.pair.lower()
        payload = self._query(
            self.CRYPTO_BASE_URL,
            tickers=ticker,
            resampleFreq="daily",
            startDate=self.config.START_DATE,
        )

        # Crypto endpoint returns array of tickers
        if isinstance(payload, list) and len(payload) > 0:
            ticker_data = payload[0]
            price_data = ticker_data.get("priceData", [])
        else:
            raise RuntimeError(f"Unexpected Tiingo crypto response: {payload}")

        rows = []
        for item in price_data:
            rows.append(
                {
                    "Date": item["date"],
                    "Open": float(item.get("open", item.get("close", 0))),
                    "High": float(item["high"]),
                    "Low": float(item["low"]),
                    "Close": float(item["close"]),
                    "Volume": float(item.get("volume", 0)),
                }
            )

        if not rows:
            raise RuntimeError(f"No price data returned for {self.pair}")

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        logger.info(f"Fetched {len(df)} rows for {self.pair}")
        return df

    def fetch_prediction_open(self, prediction_date: date) -> float:
        """Fetch opening price for prediction date.

        For today: fetch current spot price
        For past dates: fetch from historical data
        """
        try:
            if prediction_date == date.today():
                return self._fetch_current_price()
            else:
                history = self.fetch_history()
                ts = pd.Timestamp(prediction_date)
                if ts in history.index:
                    return float(history.loc[ts, "Open"])
                else:
                    logger.warning(
                        f"Date {prediction_date} not found in history, "
                        f"using most recent"
                    )
                    return float(history.iloc[-1]["Open"])
        except Exception as e:
            logger.error(f"Failed to fetch prediction open: {e}")
            raise

    def _fetch_current_price(self) -> float:
        """Fetch current spot price from Tiingo."""
        if self._is_forex():
            return self._fetch_forex_current()
        elif self._is_crypto():
            return self._fetch_crypto_current()
        else:
            raise ValueError(f"Unsupported pair: {self.pair}")

    def _fetch_forex_current(self) -> float:
        """Fetch current forex (spot) price."""
        ticker = self.pair.lower()
        payload = self._query(
            self.FOREX_PRICES_URL,
            tickers=ticker,
        )

        # Response is typically a list with ticker data
        if isinstance(payload, list) and len(payload) > 0:
            last_price = payload[0].get("last")
            if last_price is not None:
                return float(last_price)
            close = payload[0].get("close")
            if close is not None:
                return float(close)

        raise RuntimeError(f"Could not extract price from Tiingo response: {payload}")

    def _fetch_crypto_current(self) -> float:
        """Fetch current crypto price."""
        ticker = self.pair.lower()
        payload = self._query(
            self.CRYPTO_BASE_URL,
            tickers=ticker,
            resampleFreq="1min",
        )

        # Response is array with ticker data
        if isinstance(payload, list) and len(payload) > 0:
            price_data = payload[0].get("priceData", [])
            if price_data:
                latest = price_data[-1]
                return float(latest.get("close", latest.get("open", 0)))

        raise RuntimeError(f"Could not extract price from Tiingo response: {payload}")

    def sync_raw_data(self) -> Path:
        """Fetch historical data and sync with existing raw data file."""
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
                logger.info("Merged existing data with new data from Tiingo")
            except Exception as e:
                logger.error(f"Failed to merge data: {e}")
                data = history
        else:
            data = history

        data.to_csv(path)
        logger.info(f"Synced raw data → {path}")
        return path

    def fetch_actual_data(self, prediction_date: date) -> dict | None:
        """Fetch actual OHLCV data for a completed trading day.

        This is used to auto-populate actual values from API instead of manual entry.
        Returns dict with open, high, low, close, volume if available, else None.
        """
        try:
            history = self.fetch_history()
            ts = pd.Timestamp(prediction_date)

            if ts not in history.index:
                logger.warning(f"Actual data not available for {prediction_date}")
                return None

            row = history.loc[ts]
            data = {
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
            logger.info(f"Fetched actual data for {prediction_date}: {data}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch actual data for {prediction_date}: {e}")
            return None
