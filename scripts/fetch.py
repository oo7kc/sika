"""Alpha Vantage market-data fetch and local raw-data sync."""

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
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, pair: str):
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.api_key = self.config.AVS_KEY
        if not self.api_key:
            raise ValueError("Missing AVS_KEY in environment.")

    def _query(self, **params) -> dict:
        url = f"{self.BASE_URL}?{urlencode({**params, 'apikey': self.api_key})}"
        logger.info(f"Fetching Alpha Vantage data for {self.pair}")
        with urlopen(url) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if "Error Message" in payload:
            raise RuntimeError(payload["Error Message"])
        if "Information" in payload and "demo" not in payload["Information"].lower():
            raise RuntimeError(payload["Information"])
        if "Note" in payload:
            raise RuntimeError(payload["Note"])

        return payload

    def fetch_history(self) -> pd.DataFrame:
        if self.pair == "BTCUSD":
            return self._fetch_btc_history()
        if self.pair == "XAUUSD":
            return self._fetch_gold_history()
        raise ValueError(f"Unsupported pair: {self.pair}")

    def _fetch_btc_history(self) -> pd.DataFrame:
        payload = self._query(
            function="DIGITAL_CURRENCY_DAILY",
            symbol="BTC",
            market="USD",
        )
        rows = []
        for dt, values in payload["Time Series (Digital Currency Daily)"].items():
            rows.append(
                {
                    "Date": dt,
                    "Open": float(values["1. open"]),
                    "High": float(values["2. high"]),
                    "Low": float(values["3. low"]),
                    "Close": float(values["4. close"]),
                    "Volume": float(values["5. volume"]),
                }
            )
        return pd.DataFrame(rows).set_index("Date").sort_index()

    def _fetch_gold_history(self) -> pd.DataFrame:
        payload = self._query(
            function="GOLD_SILVER_HISTORY",
            symbol="GOLD",
            interval="daily",
        )
        rows = []
        for item in payload["data"]:
            price = float(item["price"])
            rows.append(
                {
                    "Date": item["date"],
                    "Open": price,
                    "High": price,
                    "Low": price,
                    "Close": price,
                    "Volume": 0.0,
                }
            )
        return pd.DataFrame(rows).set_index("Date").sort_index()

    def fetch_prediction_open(self, prediction_date: date) -> float:
        if self.pair == "BTCUSD":
            history = self._fetch_btc_history()
            key = prediction_date.isoformat()
            if key in history.index:
                return float(history.loc[key, "Open"])
            return float(history.iloc[-1]["Open"])

        if self.pair == "XAUUSD":
            if prediction_date != date.today():
                raise ValueError(
                    "Alpha Vantage does not provide historical daily open for gold here. "
                    "Use --open for past dates."
                )
            payload = self._query(function="GOLD_SILVER_SPOT", symbol="GOLD")
            if "price" not in payload:
                raise RuntimeError("Unexpected gold spot response from Alpha Vantage.")
            return float(payload["price"])

        raise ValueError(f"Unsupported pair: {self.pair}")

    def sync_raw_data(self) -> Path:
        history = self.fetch_history()
        history.index = pd.to_datetime(history.index)
        history.index.name = "Date"

        path = Path(self.paths["raw_data"])
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = pd.read_csv(path, index_col=0)
            existing.index = pd.to_datetime(existing.index, format="mixed")
            data = pd.concat([existing, history])
            data = data[~data.index.duplicated(keep="last")].sort_index()
        else:
            data = history

        data.to_csv(path)
        logger.info(f"Synced raw data → {path}")
        return path
