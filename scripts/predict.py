"""Prediction pipeline — loads artifacts, runs inference, appends to log."""

import json
from datetime import date
from pathlib import Path
from typing import Dict, Optional

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
    def __init__(self, pair: str):
        self.config = Config()
        self.pair = pair.upper()
        self.paths = self.config.get_paths(self.pair)
        self.scaler = None
        self.model = None
        self.feature_names: list = []

    def load_artifacts(self):
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
        data = load_data(
            self.paths["raw_data"], exclude_weekends=not is_crypto(self.pair)
        )
        logger.info(f"Loaded {len(data)} historical records")
        df = data.copy()
        ts = pd.Timestamp(prediction_date)
        df.loc[ts, ["Open", "High", "Low", "Close", "Volume"]] = [open_price] * 4 + [
            0.0
        ]
        return calculate_indicators(df.sort_index())

    def predict(self, data: pd.DataFrame, prediction_date: date) -> int:
        ts = pd.Timestamp(prediction_date)
        if ts not in data.index:
            raise ValueError(f"Date {prediction_date} not found in prepared data")
        X = data.loc[[ts], self.feature_names]
        X_scaled = pd.DataFrame(
            self.scaler.transform(X), columns=X.columns, index=X.index
        )
        result = int(self.model.predict(X_scaled)[0])
        logger.info(f"Prediction: {result}")
        return result

    def log_prediction(self, prediction_date: date, prediction: int, open_price: float):
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
                existing.index = pd.Index(pd.to_datetime(existing.index).date)
                log = pd.concat([existing, entry])
                log = log[~log.index.duplicated(keep="last")]
            except Exception as e:
                logger.warning(f"Could not read existing log — starting fresh: {e}")
                log = entry
        else:
            log = entry

        log.to_csv(log_path)
        logger.info(f"Logged → {log_path}")

    def run(self, open_price: float, prediction_date: Optional[date] = None) -> Dict:
        if prediction_date is None:
            prediction_date = date.today()

        logger.info(
            f"=== Prediction start: {self.pair} | {prediction_date} | open={open_price} ==="
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
