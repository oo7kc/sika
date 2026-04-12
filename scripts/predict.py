"""Prediction pipeline for running trained models and logging predictions."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from config import Config
from scripts.data import is_crypto, load_data
from scripts.display import SIGNAL_LABELS
from scripts.indicators import calculate_indicators
from scripts.logger import get_logger

logger = get_logger(__name__)


class PredictionPipeline:
    """Pipeline for making predictions using trained ML models.

    Loads saved model and scaler artifacts, prepares historical data,
    runs inference, and logs predictions to a CSV file for later
    evaluation.
    """

    def __init__(self, pair: str) -> None:
        """Initialize the prediction pipeline for a trading pair.

        Args:
            pair: Trading pair symbol (e.g., "XAUUSD").
        """
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.scaler = None
        self.model = None
        self.feature_names: list[str] = []

    def load_artifacts(self) -> None:
        """Load trained model, scaler, and feature metadata.

        Loads serialized artifacts from disk:
        - MLPClassifier model
        - MinMaxScaler for feature normalization
        - Feature names metadata (optional)

        Falls back to config SELECTED_FEATURES if metadata not found.

        Raises:
            FileNotFoundError: If model or scaler file is missing.
        """
        model_path = Path(self.paths["model"])
        scaler_path = Path(self.paths["scaler"])

        if not model_path.exists():
            raise FileNotFoundError(
                f"No trained model at {model_path}. Run training first."
            )
        if not scaler_path.exists():
            raise FileNotFoundError(f"No scaler at {scaler_path}. Run training first.")

        self.model = joblib.load(model_path)
        self.scaler = joblib.load(scaler_path)
        logger.info(f"Artifacts loaded for {self.pair}")

        meta_path = Path(self.paths["metadata"])
        if meta_path.exists():
            with open(meta_path) as f:
                self.feature_names = json.load(f).get(
                    "feature_names", self.config.SELECTED_FEATURES
                )
        else:
            logger.warning("Metadata not found — using config features")
            self.feature_names = self.config.SELECTED_FEATURES

    def prepare_data(self, prediction_date: date, open_price: float) -> pd.DataFrame:
        """Load and prepare data for inference.

        Loads historical OHLCV data, computes all technical indicators,
        and returns data with indicators ready for feature extraction.
        Only includes data completed before the prediction_date to avoid
        look-ahead bias.

        Args:
            prediction_date: Date to make prediction for.
            open_price: Opening price (informational, not used in computation).

        Returns:
            DataFrame with DateTime index and all indicator columns.

        Raises:
            ValueError: If no completed historical data exists before the date.
        """
        data = load_data(
            self.paths["raw_data"], exclude_weekends=not is_crypto(self.pair)
        )
        logger.info(f"Loaded {len(data)} historical records")
        ts = pd.Timestamp(prediction_date)
        history = data[data.index < ts].copy()
        if history.empty:
            raise ValueError(
                f"No completed historical data available before {prediction_date}"
            )
        max_date = history.index.max().date()  # type: ignore
        logger.info(f"Using latest completed bar from {max_date} for inference")
        return calculate_indicators(history.sort_index())  # type: ignore

    def predict(self, data: pd.DataFrame, prediction_date: date) -> int:
        """Run the trained model on prepared data.

        Extracts the latest feature vector, scales it using the saved scaler,
        and runs the model to produce a prediction.

        Args:
            data: DataFrame with computed indicator columns.
            prediction_date: Date being predicted (for logging).

        Returns:
            Predicted signal: -1 (down), 0 (hold), or 1 (up).

        Raises:
            ValueError: If features cannot be extracted (NaN values or missing data).
            RuntimeError: If model or scaler not loaded.
        """
        if self.model is None or self.scaler is None:
            raise RuntimeError(
                "Model and scaler must be loaded via load_artifacts() first"
            )
        X = data[self.feature_names].tail(1).dropna()
        if X.empty:
            raise ValueError(
                f"Not enough history to build features for {prediction_date}"
            )
        X_scaled = pd.DataFrame(
            self.scaler.transform(X), columns=X.columns, index=X.index
        )
        result = int(self.model.predict(X_scaled)[0])
        logger.info(f"Prediction: {result}")
        return result

    def log_prediction(
        self, prediction_date: date, prediction: int, open_price: float
    ) -> None:
        """Log the prediction to CSV for later evaluation.

        Appends a new entry or updates an existing one in the prediction log.
        Prevents duplicate predictions for the same date.

        Args:
            prediction_date: Date of the prediction.
            prediction: Predicted signal value (-1, 0, 1).
            open_price: Opening price at prediction time.

        Raises:
            ValueError: If prediction for this date already exists.
        """
        log_path = Path(self.paths["log"])
        log_path.parent.mkdir(parents=True, exist_ok=True)

        entry = pd.DataFrame(
            {
                "Date": [prediction_date],
                "Open": [open_price],
                "Predicted": [prediction],
                "Actual": [np.nan],
                "Correct": [np.nan],
            }
        ).set_index("Date")

        if log_path.exists():
            try:
                existing = pd.read_csv(log_path, index_col=0, parse_dates=[0])
                existing.index = pd.Index(pd.to_datetime(existing.index).dt.date)  # type: ignore
                if prediction_date in existing.index and not pd.isna(
                    existing.loc[prediction_date, "Actual"]
                ):
                    raise ValueError(
                        f"Prediction for {prediction_date} is already completed in "
                        f"the log."
                    )
                if prediction_date in existing.index:
                    raise ValueError(
                        f"Prediction for {prediction_date} already exists in the log."
                    )
                log = pd.concat([existing, entry])
            except Exception as e:
                if isinstance(e, ValueError):
                    raise
                logger.warning(f"Could not read existing log — starting fresh: {e}")
                log = entry
        else:
            log = entry

        log.to_csv(log_path)
        logger.info(f"Logged → {log_path}")

    def run(
        self, open_price: float, prediction_date: date | None = None
    ) -> dict[str, Any]:
        """Execute the complete prediction pipeline.

        Loads artifacts, prepares data, runs inference, logs the prediction,
        and returns results with interpretation labels.

        Args:
            open_price: Current opening or spot price.
            prediction_date: Date to predict for. Defaults to today.

        Returns:
            Dictionary with:
                - pair: Trading pair symbol
                - date: Prediction date
                - open_price: Input opening price
                - prediction: Signal value (-1, 0, 1)
                - action: Text interpretation of signal
                - emoji: Emoji for the signal
                - color: Display color for the signal

        Raises:
            FileNotFoundError: If model or scaler not found.
            ValueError: If insufficient data or duplicate prediction.
            RuntimeError: If any pipeline step fails.
        """
        if prediction_date is None:
            prediction_date = date.today()

        logger.info(
            f"=== Prediction start: {self.pair} | {prediction_date} | "
            f"open={open_price} ==="
        )
        self.load_artifacts()
        data = self.prepare_data(prediction_date, open_price)
        prediction = self.predict(data, prediction_date)
        self.log_prediction(prediction_date, prediction, open_price)

        sig = SIGNAL_LABELS.get(
            prediction, {"action": "Unknown", "emoji": "❓", "color": "white"}
        )
        logger.info(f"=== Prediction done: {self.pair} → {sig['action']} ===")

        return {
            "pair": self.pair,
            "date": prediction_date,
            "open_price": open_price,
            "prediction": prediction,
            **sig,
        }


if __name__ == "__main__":
    result = PredictionPipeline(pair="XAUUSD").run(open_price=2650.50)
    print(f"Prediction: {result['prediction']} — {result['action']}")
