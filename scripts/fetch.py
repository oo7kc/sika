"""Tiingo market data API client for historical and real-time prices."""

from datetime import date
from pathlib import Path

import pandas as pd
import requests

from config import Config
from scripts.logger import get_logger

logger = get_logger(__name__)


class MarketDataPipeline:
    """Fetch market data from Tiingo API and sync with local storage.

    Supports cryptocurrency (BTCUSD) pairs, forex (XAUUSD) pairs with
    historical data fetching, current price queries, and local file syncing.
    """

    CRYPTO_PRICES_URL = "https://api.tiingo.com/tiingo/crypto/prices"
    FX_PRICES_URL = "https://api.tiingo.com/tiingo/fx/{ticker}/prices"

    def __init__(self, pair: str) -> None:
        """Initialize the market data pipeline for a trading pair.

        Args:
            pair: Trading pair symbol (e.g., "BTCUSD", "XAUUSD").

        Raises:
            ValueError: If TIINGO_KEY is not set in configuration.
        """
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.api_key = self.config.TIINGO_KEY
        if not self.api_key:
            raise ValueError("Missing TIINGO_KEY in environment.")

    def _is_crypto(self) -> bool:
        """Check if the pair is a cryptocurrency pair."""
        return self.pair in ["BTCUSD"]

    def _is_forex(self) -> bool:
        """Check if the pair is a forex (FX) pair.

        Conservative rule: treat any pair that ends with 'USD' and is not
        recognized as crypto as FX.
        """
        return self.pair.endswith("USD") and not self._is_crypto()

    def _query(self, url: str, **params) -> dict | list:
        """Execute HTTP GET request to Tiingo API.

        Args:
            url: Tiingo API endpoint URL.
            **params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: If request fails.
        """
        params["token"] = self.api_key
        logger.info("Fetching from Tiingo...")

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP {e.response.status_code}: {e.response.text}")
            raise RuntimeError(f"Tiingo HTTP error: {e.response.status_code}") from e
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise RuntimeError(f"Failed to fetch from Tiingo: {e}") from e

    def fetch_history(self) -> pd.DataFrame:
        """Fetch historical OHLCV data from Tiingo.

        Returns:
            DataFrame with DateTime index and OHLCV columns.

        Raises:
            ValueError: If pair is not supported.
            RuntimeError: If API response is malformed.
        """
        if self._is_crypto():
            return self._fetch_crypto_history()
        elif self._is_forex():
            return self._fetch_fx_history()
        else:
            raise ValueError(f"Unsupported pair: {self.pair}")

    def _extract_price_data(self, payload) -> list:
        """Normalize Tiingo payload into a flat list of bar dicts.

        Handles several payload shapes:
        - Direct list of bars: [ {date, open, high, low, close, ...}, ... ]
        - List with dict containing 'priceData': [ { 'ticker':..., 'priceData': [...] }, ... ]
        - Dict with 'priceData': { 'priceData': [...] }
        """  # noqa: E501
        if not payload:
            return []

        if isinstance(payload, list):
            if (
                len(payload) > 0
                and isinstance(payload[0], dict)
                and "date" in payload[0]
            ):
                return payload
            first = payload[0]
            if isinstance(first, dict) and "priceData" in first:
                return first.get("priceData", [])
            return []

        if isinstance(payload, dict) and "priceData" in payload:
            return payload.get("priceData", [])

        return []

    def _fetch_crypto_history(self) -> pd.DataFrame:
        """Fetch cryptocurrency historical data."""
        ticker = self.pair.lower()

        payload = self._query(
            self.CRYPTO_PRICES_URL,
            tickers=ticker,
            startDate=self.config.START_DATE,
            resampleFreq="1Day",
        )

        price_data = self._extract_price_data(payload)

        if not price_data:
            logger.warning(f"No price data returned for {self.pair}")
            raise RuntimeError(f"No price data available for {self.pair}")

        rows = []
        for item in price_data:
            try:
                rows.append(
                    {
                        "Date": item.get("date"),
                        "Open": float(item.get("open", item.get("close", 0))),
                        "High": float(item.get("high", 0)),
                        "Low": float(item.get("low", 0)),
                        "Close": float(item.get("close", 0)),
                        "Volume": float(item.get("volume", 0)),
                    }
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed row: {e}")
                continue

        if not rows:
            raise RuntimeError(f"No valid data parsed for {self.pair}")

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        logger.info(f"Fetched {len(df)} rows for {self.pair}")
        return df

    def _fetch_fx_history(self) -> pd.DataFrame:
        """Fetch FX historical data using Tiingo's /tiingo/fx/<ticker>/prices endpoint.

        If that endpoint returns nothing, fall back to /tiingo/fx/historical.
        """
        ticker = self.pair.lower()
        url = self.FX_PRICES_URL.format(ticker=ticker)

        payload = None
        try:
            payload = self._query(
                url,
                startDate=self.config.START_DATE,
                resampleFreq="1Day",
            )
        except RuntimeError as e:
            logger.debug(f"FX template endpoint failed: {e}")

        price_data = self._extract_price_data(payload)

        if not price_data:
            logger.warning(f"No FX price data returned for {self.pair}")
            raise RuntimeError(f"No FX price data available for {self.pair}")

        rows = []
        for item in price_data:
            try:
                rows.append(
                    {
                        "Date": item.get("date"),
                        "Open": float(item.get("open", item.get("close", 0))),
                        "High": float(item.get("high", 0)),
                        "Low": float(item.get("low", 0)),
                        "Close": float(item.get("close", 0)),
                        "Volume": float(item.get("volume", 0) or 0),
                    }
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Skipping malformed FX row: {e}")
                continue

        if not rows:
            raise RuntimeError(f"No valid FX data parsed for {self.pair}")

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        logger.info(f"Fetched {len(df)} rows for FX {self.pair}")
        return df

    def fetch_prediction_open(self, prediction_date: date) -> float:
        """Fetch opening price for prediction date.

        For today: fetches current price.
        For past dates: fetches from historical data.

        Args:
            prediction_date: Date to fetch price for.

        Returns:
            Opening price as float.

        Raises:
            RuntimeError: If price cannot be fetched.
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
                        f"Date {prediction_date} not found, using most recent price"
                    )
                    return float(history.iloc[-1]["Open"])
        except Exception as e:
            logger.error(f"Failed to fetch prediction open: {e}")
            raise

    def _fetch_current_price(self) -> float:
        """Fetch current spot price from Tiingo.

        Returns:
            Current price as float.

        Raises:
            RuntimeError: If price cannot be fetched.
        """
        ticker = self.pair.lower()

        if self._is_crypto():
            payload = self._query(
                self.CRYPTO_PRICES_URL,
                tickers=ticker,
                resampleFreq="1Min",
            )
            price_data = self._extract_price_data(payload)
            if price_data:
                latest = price_data[-1]
                return float(latest.get("close", latest.get("open", 0)))

        if self._is_forex():
            url = self.FX_PRICES_URL.format(ticker=ticker)
            payload = self._query(
                url, resampleFreq="1Min", startDate=self.config.START_DATE
            )
            price_data = self._extract_price_data(payload)
            if price_data:
                latest = price_data[-1]
                return float(latest.get("close", latest.get("open", 0)))

        raise RuntimeError(f"Could not fetch current price for {self.pair}")

    def sync_raw_data(self) -> Path:
        """Fetch historical data and sync with existing raw data file.

        Returns:
            Path to the synced raw data file.

        Raises:
            RuntimeError: If file cannot be written.
        """
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

        try:
            data.to_csv(path)
            logger.info(f"Synced raw data → {path}")
            return path
        except Exception as e:
            logger.error(f"Failed to write raw data: {e}")
            raise RuntimeError(f"Could not write raw data: {e}") from e

    def fetch_actual_data(self, prediction_date: date) -> dict | None:
        """Fetch actual OHLCV data for a completed trading day.

        Returns:
            Dict with open, high, low, close, volume if available, else None.
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
