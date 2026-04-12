"""Logging pipeline — records OHLCV values and tracks prediction accuracy."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from config import Config
from scripts.data import is_crypto, load_data
from scripts.logger import get_logger

logger = get_logger(__name__)


class LoggingPipeline:
    """Track and log prediction results with accuracy metrics."""

    def __init__(self, pair: str) -> None:
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.log_path = Path(self.paths["log"])

    def load_prediction_log(self) -> pd.DataFrame:
        """Load prediction log from CSV."""
        if not self.log_path.exists():
            raise FileNotFoundError(
                f"No prediction log at {self.log_path}. Make predictions first."
            )
        log = pd.read_csv(self.log_path, index_col=0, parse_dates=[0])
        log.index = pd.Index(pd.to_datetime(log.index).dt.date)  # type: ignore
        log.index.name = "Date"
        return log

    def get_pending_predictions(self, log: pd.DataFrame) -> pd.DataFrame:
        """Return predictions awaiting actuals."""
        return log[log["Actual"].isna()]  # type: ignore[return-value]

    def update_log(
        self, log: pd.DataFrame, prediction_date: date, actual: int
    ) -> pd.DataFrame:
        """Update log with actual value and correctness."""
        if prediction_date not in log.index:
            raise ValueError(f"No prediction found for {prediction_date}")
        log.loc[prediction_date, "Actual"] = actual
        log.loc[prediction_date, "Correct"] = int(
            log.loc[prediction_date, "Predicted"] == actual
        )
        return log

    def save_prediction_log(self, log: pd.DataFrame) -> None:
        """Save prediction log to CSV."""
        log.to_csv(self.log_path)

    def _resolve_actuals(
        self,
        prediction_date: date,
        high: float | None,
        low: float | None,
        close: float | None,
        volume: float | None,
    ) -> tuple[dict, bool]:
        """Fetch OHLCV from API or use caller-supplied values.

        Returns (ohlcv, was_auto_fetched).
        """
        try:
            from scripts.fetch import MarketDataPipeline

            fetched = MarketDataPipeline(self.pair).fetch_actuals_for_date(
                prediction_date
            )
            if fetched:
                return fetched, True
        except Exception as e:
            msg = f"Auto-fetch failed — falling back to manual values: {e}"
            logger.warning(msg)

        if None in (high, low, close):
            raise ValueError(
                f"Actuals not available from API for {prediction_date} and "
                "high/low/close were not provided manually."
            )
        return {
            "open": None,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume or 0.0,
        }, False

    def update_raw_data(
        self,
        prediction_date: date,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Write completed OHLCV bar to raw data CSV."""
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
        else:
            new_row = pd.DataFrame([row], index=[ts])  # type: ignore[arg-type]
            data = pd.concat([data, new_row]).sort_index()  # type: ignore

        try:
            data.to_csv(self.paths["raw_data"])
        except Exception as e:
            raise RuntimeError(f"Could not write raw data: {e}") from e

    def calculate_accuracy_metrics(self, log: pd.DataFrame) -> dict:
        """Calculate overall and rolling accuracy metrics."""
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
            "rolling_accuracy_10": (
                completed.tail(10)["Correct"].mean() * 100 if n >= 10 else overall
            ),
            "rolling_accuracy_30": (
                completed.tail(30)["Correct"].mean() * 100 if n >= 30 else overall
            ),
        }

    def get_accuracy_by_prediction_type(self, log: pd.DataFrame) -> dict:
        """Return accuracy metrics grouped by prediction type (-1, 0, 1)."""
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

    def run(
        self,
        prediction_date: date,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
        volume: float | None = None,
    ) -> dict:
        """Log actuals for a prediction date.

        Auto-fetch from API or use supplied values.
        """
        msg = f"=== Logging start: {self.pair} | {prediction_date} ==="
        logger.info(msg)

        log = self.load_prediction_log()

        if prediction_date not in log.index:
            raise ValueError(
                f"No prediction for {prediction_date}. Make a prediction first."
            )
        if "Open" not in log.columns or pd.isna(log.loc[prediction_date, "Open"]):
            raise ValueError(f"Open price missing for {prediction_date} in log.")

        open_price = float(log.loc[prediction_date, "Open"])

        actuals, auto_fetched = self._resolve_actuals(
            prediction_date, high, low, close, volume
        )

        actual_close = actuals["close"]
        actual_high = actuals["high"]
        actual_low = actuals["low"]
        actual_volume = actuals["volume"] or 0.0
        actual_gamma = int(np.sign(actual_close - open_price))

        fetch_mode = "auto" if auto_fetched else "manual"
        msg = (
            f"O={open_price:.4f}  H={actual_high:.4f}  "
            f"L={actual_low:.4f}  C={actual_close:.4f}  "
            f"V={actual_volume:.0f}  Γ={actual_gamma}  ({fetch_mode})"
        )
        logger.info(msg)

        log = self.update_log(log, prediction_date, actual_gamma)
        self.save_prediction_log(log)
        self.update_raw_data(
            prediction_date,
            open_price,
            actual_high,
            actual_low,
            actual_close,
            actual_volume,
        )

        metrics = self.calculate_accuracy_metrics(log)
        accuracy_pct = metrics["overall_accuracy"]
        correct_count = metrics["correct_count"]
        completed_count = metrics["completed_predictions"]
        log_msg = (
            f"=== Logging done: {self.pair} | "
            f"accuracy {accuracy_pct:.2f}% "
            f"({correct_count}/{completed_count}) ==="
        )
        logger.info(log_msg)

        return {
            "pair": self.pair,
            "date": prediction_date,
            "open_price": open_price,
            "high": actual_high,
            "low": actual_low,
            "close": actual_close,
            "volume": actual_volume,
            "actuals_auto_fetched": auto_fetched,
            "predicted": int(log.loc[prediction_date, "Predicted"]),
            "actual": actual_gamma,
            "correct": log.loc[prediction_date, "Correct"] == 1,
            "metrics": metrics,
            "accuracy_by_type": self.get_accuracy_by_prediction_type(log),
        }


if __name__ == "__main__":
    result = LoggingPipeline(pair="XAUUSD").run(prediction_date=date(2024, 11, 22))
    correct_str = "CORRECT" if result["correct"] else "INCORRECT"
    accuracy = result["metrics"]["overall_accuracy"]
    print(f"{correct_str} — {accuracy:.2f}%")
