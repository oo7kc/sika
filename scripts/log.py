"""Logging pipeline — records actual OHLCV values and tracks prediction accuracy."""

from datetime import date
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from config import Config
from scripts.data import is_crypto, load_data
from scripts.logger import get_logger

logger = get_logger(__name__)


class LoggingPipeline:
    def __init__(self, pair: str):
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.log_path = Path(self.paths["log"])

    # / Log helpers /

    def load_prediction_log(self) -> pd.DataFrame:
        if not self.log_path.exists():
            raise FileNotFoundError(
                f"No prediction log at {self.log_path}. Make predictions first."
            )
        log = pd.read_csv(self.log_path, index_col=0, parse_dates=[0])
        log.index = pd.Index(pd.to_datetime(log.index).date)
        log.index.name = "Date"
        logger.info(f"Loaded log — {len(log)} entries")
        return log

    def get_pending_predictions(self, log: pd.DataFrame) -> pd.DataFrame:
        pending = log[log["Actual"].isna()]
        logger.info(f"{len(pending)} prediction(s) pending")
        return pending

    def update_log(
        self, log: pd.DataFrame, prediction_date: date, actual: int
    ) -> pd.DataFrame:
        if prediction_date not in log.index:
            raise ValueError(f"No prediction found for {prediction_date}")
        log.loc[prediction_date, "Actual"] = actual
        log.loc[prediction_date, "Correct"] = int(
            log.loc[prediction_date, "Predicted"] == actual
        )
        return log

    def save_prediction_log(self, log: pd.DataFrame):
        log.to_csv(self.log_path)
        logger.info(f"Log saved → {self.log_path}")

    # / Raw data update — raises on failure so callers know it didn't persist /

    def update_raw_data(
        self,
        prediction_date: date,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ):
        """Write the completed OHLCV bar back into the raw CSV.

        Raises:
            RuntimeError: if the file cannot be read or written.
        """
        try:
            data = load_data(
                self.paths["raw_data"], exclude_weekends=not is_crypto(self.pair)
            )
        except Exception as e:
            raise RuntimeError(f"Could not load raw data for update: {e}") from e

        ts = pd.Timestamp(prediction_date)
        row = {
            "Open": open_price,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        }

        if ts in data.index:
            for col, val in row.items():
                data.loc[ts, col] = val
            logger.info(f"Updated existing raw-data entry for {prediction_date}")
        else:
            data = pd.concat([data, pd.DataFrame(row, index=[ts])]).sort_index()
            logger.info(f"Appended new raw-data entry for {prediction_date}")

        try:
            data.to_csv(self.paths["raw_data"])
            logger.info(f"Raw data saved → {self.paths['raw_data']}")
        except Exception as e:
            raise RuntimeError(f"Could not write raw data: {e}") from e

    # / Accuracy metrics /

    def calculate_accuracy_metrics(self, log: pd.DataFrame) -> Dict:
        completed = log[log["Correct"].notna()]
        n = len(completed)
        if n == 0:
            return {
                "total_predictions": len(log),
                "completed_predictions": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "overall_accuracy": 0.0,
                "rolling_accuracy_10": 0.0,
                "rolling_accuracy_30": 0.0,
            }
        correct = int(completed["Correct"].sum())
        overall = correct / n * 100
        return {
            "total_predictions": len(log),
            "completed_predictions": n,
            "correct_count": correct,
            "incorrect_count": n - correct,
            "overall_accuracy": overall,
            "rolling_accuracy_10": completed.tail(10)["Correct"].mean() * 100
            if n >= 10
            else overall,
            "rolling_accuracy_30": completed.tail(30)["Correct"].mean() * 100
            if n >= 30
            else overall,
        }

    def get_accuracy_by_prediction_type(self, log: pd.DataFrame) -> Dict:
        completed = log[log["Correct"].notna()]
        return {
            sig: {
                "count": len(s),
                "correct": int(s["Correct"].sum()),
                "accuracy": s["Correct"].mean() * 100,
            }
            for sig in [-1, 0, 1]
            if len(s := completed[completed["Predicted"] == sig]) > 0
        }

    # / Entry point /

    def run(
        self,
        prediction_date: date,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> Dict:
        logger.info(f"=== Logging start: {self.pair} | {prediction_date} ===")

        log = self.load_prediction_log()

        if prediction_date not in log.index:
            raise ValueError(
                f"No prediction for {prediction_date}. Make a prediction first."
            )

        if "Open" not in log.columns or pd.isna(log.loc[prediction_date, "Open"]):
            raise ValueError(f"Open price missing for {prediction_date} in the log.")

        open_price = float(log.loc[prediction_date, "Open"])
        actual = int(np.sign(close - open_price))
        logger.info(f"Open={open_price:.4f}  Close={close:.4f}  Gamma={actual}")

        log = self.update_log(log, prediction_date, actual)
        self.save_prediction_log(log)
        self.update_raw_data(prediction_date, open_price, high, low, close, volume)

        logger.info(f"=== Logging done: {self.pair} ===")

        return {
            "pair": self.pair,
            "date": prediction_date,
            "open_price": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "predicted": int(log.loc[prediction_date, "Predicted"]),
            "actual": actual,
            "correct": log.loc[prediction_date, "Correct"] == 1,
            "metrics": self.calculate_accuracy_metrics(log),
            "accuracy_by_type": self.get_accuracy_by_prediction_type(log),
        }


if __name__ == "__main__":
    result = LoggingPipeline(pair="XAUUSD").run(
        prediction_date=date(2024, 11, 22),
        high=2650.80,
        low=2645.20,
        close=2648.50,
        volume=15000,
    )
    print(
        f"{'CORRECT' if result['correct'] else 'INCORRECT'} — {result['metrics']['overall_accuracy']:.2f}%"
    )
