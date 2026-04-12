"""Logging pipeline for recording actual OHLCV values and tracking accuracy."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from config import Config
from scripts.data import is_crypto, load_data
from scripts.fetch import MarketDataPipeline
from scripts.logger import get_logger

logger = get_logger(__name__)


class LoggingPipeline:
    """Log actual market data and track prediction accuracy metrics.

    Maintains a CSV log of predictions with actual values and correctness flags.
    Calculates overall and per-signal-type accuracy statistics. Can optionally
    fetch actual data from Tiingo API.
    """

    def __init__(self, pair: str) -> None:
        """Initialize the logging pipeline for a trading pair.

        Args:
            pair: Trading pair symbol (e.g., "XAUUSD").
        """
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.log_path = Path(self.paths["log"])

    def load_prediction_log(self) -> pd.DataFrame:
        """Load the prediction log CSV file.

        Returns:
            DataFrame with columns Date, Open, Predicted, Actual, Correct.

        Raises:
            FileNotFoundError: If no prediction log exists for this pair.
        """
        if not self.log_path.exists():
            raise FileNotFoundError(
                f"No prediction log at {self.log_path}. Make predictions first."
            )
        log = pd.read_csv(self.log_path, index_col=0, parse_dates=[0])
        log.index = pd.Index(pd.to_datetime(log.index).dt.date)  # type: ignore
        log.index.name = "Date"
        logger.info(f"Loaded log — {len(log)} entries")
        return log

    def get_pending_predictions(self, log: pd.DataFrame) -> pd.DataFrame:
        """Get predictions that have not yet been logged with actual values.

        Args:
            log: Prediction log DataFrame.

        Returns:
            Subset of log where Actual column is NaN.
        """
        pending = log[log["Actual"].isna()]
        logger.info(f"{len(pending)} prediction(s) pending")
        return pending  # type: ignore

    def update_log(
        self,
        log: pd.DataFrame,
        prediction_date: date,
        actual: int,
    ) -> pd.DataFrame:
        """Update log with actual values and correctness for a prediction.

        Args:
            log: Prediction log DataFrame.
            prediction_date: Date of the prediction to update.
            actual: Actual signal value (-1, 0, or 1).

        Returns:
            Updated log DataFrame.

        Raises:
            ValueError: If no prediction exists for the given date.
        """
        if prediction_date not in log.index:
            raise ValueError(f"No prediction found for {prediction_date}")
        log.loc[prediction_date, "Actual"] = actual
        log.loc[prediction_date, "Correct"] = int(
            log.loc[prediction_date, "Predicted"] == actual
        )
        return log

    @staticmethod
    def validate_ohlc(
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Validate OHLCV data integrity.

        Ensures that:
        - Low <= Open/Close <= High
        - Volume >= 0

        Args:
            open_price: Opening price.
            high: High price.
            low: Low price.
            close: Closing price.
            volume: Trading volume.

        Raises:
            ValueError: If any OHLCV constraint is violated.
        """
        if low > high:
            raise ValueError("Low price cannot be greater than high price.")
        if not low <= open_price <= high:
            raise ValueError("Open price must be between low and high.")
        if not low <= close <= high:
            raise ValueError("Close price must be between low and high.")
        if volume < 0:
            raise ValueError("Volume cannot be negative.")

    def save_prediction_log(self, log: pd.DataFrame) -> None:
        """Save the prediction log to CSV file.

        Args:
            log: Prediction log DataFrame.
        """
        log.to_csv(self.log_path)
        logger.info(f"Log saved → {self.log_path}")

    def try_fetch_actuals(self, prediction_date: date) -> dict[str, float] | None:
        """Attempt to fetch actual OHLCV data from Tiingo API.

        If successful, returns a dict that can be used to populate actual values
        instead of requiring manual entry.

        Args:
            prediction_date: Date to fetch actual data for.

        Returns:
            Dictionary with {open, high, low, close, volume} if available,
            None if fetch fails or data not available.
        """
        try:
            pipeline = MarketDataPipeline(pair=self.pair)
            actual_data = pipeline.fetch_actual_data(prediction_date)
            if actual_data:
                logger.info(
                    f"Fetched actual data from Tiingo API for {prediction_date}"
                )
                return actual_data
        except Exception as e:
            logger.warning(f"Could not fetch actuals from API: {e}")
        return None

    def update_raw_data(
        self,
        prediction_date: date,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Write completed OHLCV bar into the raw data CSV file.

        Updates an existing row if the date exists, or appends a new row.
        Raises on any error so that the caller knows the update did not persist.

        Args:
            prediction_date: Date of the bar to write.
            open_price: Opening price.
            high: High price.
            low: Low price.
            close: Closing price.
            volume: Trading volume.

        Raises:
            RuntimeError: If raw data cannot be read or written.
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
            data = pd.concat([data, pd.DataFrame(row, index=[ts])]).sort_index()  # type: ignore
            logger.info(f"Appended new raw-data entry for {prediction_date}")

        try:
            data.to_csv(self.paths["raw_data"])
            logger.info(f"Raw data saved → {self.paths['raw_data']}")
        except Exception as e:
            raise RuntimeError(f"Could not write raw data: {e}") from e

    def calculate_accuracy_metrics(self, log: pd.DataFrame) -> dict[str, float]:
        """Calculate overall accuracy metrics from the prediction log.

        Includes overall accuracy and rolling accuracies (last 10 and 30 predictions).

        Args:
            log: Prediction log DataFrame.

        Returns:
            Dictionary with keys:
                - total_predictions: Total predictions ever made
                - completed_predictions: Predictions with actual values logged
                - correct_count: Number of correct predictions
                - incorrect_count: Number of incorrect predictions
                - overall_accuracy: Accuracy percentage
                - rolling_accuracy_10: Last 10 predictions accuracy
                - rolling_accuracy_30: Last 30 predictions accuracy
        """
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

    def get_accuracy_by_prediction_type(
        self,
        log: pd.DataFrame,
    ) -> dict[int, dict[str, float]]:
        """Calculate accuracy metrics broken down by prediction signal type.

        Args:
            log: Prediction log DataFrame.

        Returns:
            Dictionary mapping signal (-1, 0, 1) to accuracy stats:
                - count: Number of that signal type
                - correct: Number correct for that signal
                - accuracy: Accuracy percentage for that signal
        """
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
        """Log actual values for a prediction and update accuracy metrics.

        Loads the prediction log, validates OHLCV data, updates the log with
        actual values and correctness, updates raw data, and calculates metrics.

        Can auto-fetch actual data from Tiingo API if values not provided.

        Args:
            prediction_date: Date of the prediction to log.
            high: High price. If None, attempts to fetch from API.
            low: Low price. If None, attempts to fetch from API.
            close: Close price. If None, attempts to fetch from API.
            volume: Volume. If None, attempts to fetch from API.

        Returns:
            Dictionary with:
                - pair, date, open_price, high, low, close, volume: Market data
                - data_source: "manual" or "api"
                - predicted, actual: Signal values (-1, 0, 1)
                - correct: Boolean indicating if prediction was correct
                - metrics: Overall accuracy metrics
                - accuracy_by_type: Per-signal-type accuracy breakdown

        Raises:
            FileNotFoundError: If no prediction log exists.
            ValueError: If no prediction found for date or OHLCV validation fails.
            RuntimeError: If raw data cannot be updated.
        """
        logger.info(f"=== Logging start: {self.pair} | {prediction_date} ===")

        log = self.load_prediction_log()

        if prediction_date not in log.index:
            raise ValueError(
                f"No prediction for {prediction_date}. Make a prediction first."
            )

        if "Open" not in log.columns or pd.isna(log.loc[prediction_date, "Open"]):
            raise ValueError(f"Open price missing for {prediction_date} in the log.")

        open_price = float(log.loc[prediction_date, "Open"])

        data_source = "manual"
        if high is None or low is None or close is None or volume is None:
            api_data = self.try_fetch_actuals(prediction_date)
            if api_data:
                high = api_data["high"]
                low = api_data["low"]
                close = api_data["close"]
                volume = api_data["volume"]
                data_source = "api"
                logger.info("Using actual data from Tiingo API")
            else:
                raise ValueError(
                    f"No actual data available from API for {prediction_date}. "
                    "Please provide manual OHLCV values."
                )

        if high is None or low is None or close is None or volume is None:
            raise ValueError("OHLCV values cannot be None")
        high = float(high)
        low = float(low)
        close = float(close)
        volume = float(volume)
        self.validate_ohlc(open_price, high, low, close, volume)

        actual = int(np.sign(close - open_price))
        logger.info(
            f"Open={open_price:.4f}  Close={close:.4f}  Gamma={actual} "
            f"(source: {data_source})"
        )

        log = self.update_log(log, prediction_date, actual)
        self.update_raw_data(prediction_date, open_price, high, low, close, volume)
        self.save_prediction_log(log)

        logger.info(f"=== Logging done: {self.pair} ===")

        return {
            "pair": self.pair,
            "date": prediction_date,
            "open_price": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "data_source": data_source,
            "predicted": int(log.loc[prediction_date, "Predicted"]),
            "actual": actual,
            "correct": bool(log.loc[prediction_date, "Correct"] == 1),
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
        f"{'CORRECT' if result['correct'] else 'INCORRECT'} — "
        f"{result['metrics']['overall_accuracy']:.2f}%"
    )
