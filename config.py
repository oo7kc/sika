"""Central configuration — all values overridable via environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Trading pipeline configuration."""

    RAW_DATA_DIR = os.getenv("RAW_DATA_DIR", "data/raw")
    PROCESSED_DATA_DIR = os.getenv("PROCESSED_DATA_DIR", "data/processed")
    MODEL_DIR = os.getenv("MODEL_DIR", "models")
    LOGS_DIR = os.getenv("LOGS_DIR", "logs")

    TIINGO_KEY = os.getenv("TIINGO_KEY", "")

    TRADING_PAIRS = [p.strip() for p in os.getenv("TRADING_PAIRS", "XAUUSD").split(",")]

    START_DATE = os.getenv("START_DATE", "2020-01-01")

    RANDOM_STATE = int(os.getenv("RANDOM_STATE", "42"))
    TRAIN_SPLIT = float(os.getenv("TRAIN_SPLIT", "0.8"))
    ACTIVATION = os.getenv("ACTIVATION", "logistic")
    SOLVER = os.getenv("SOLVER", "lbfgs")
    LEARNING_RATE = os.getenv("LEARNING_RATE", "adaptive")
    LEARNING_RATE_INIT = float(os.getenv("LEARNING_RATE_INIT", "0.03"))
    MAX_ITER = int(os.getenv("MAX_ITER", "10000"))
    MOMENTUM = float(os.getenv("MOMENTUM", "0.2"))
    EARLY_STOPPING = os.getenv("EARLY_STOPPING", "True").lower() == "true"

    SELECTED_FEATURES = [
        f.strip()
        for f in os.getenv(
            "SELECTED_FEATURES",
            "TTM_TRND_6,MACD_12_26_9,RSI_14,ADX_14,STOCHRSIk_10_14_3_3,INC_1,DEC_1",
        ).split(",")
    ]

    @classmethod
    def get_paths(cls, pair: str) -> dict:
        """Return file paths for a trading pair."""
        pair = pair.upper()
        return {
            "raw_data": os.path.join(cls.RAW_DATA_DIR, f"{pair}RAW.csv"),
            "model": os.path.join(cls.MODEL_DIR, f"{pair}_mlp_classifier.pkl"),
            "scaler": os.path.join(cls.MODEL_DIR, f"{pair}_scaler.pkl"),
            "metadata": os.path.join(cls.MODEL_DIR, f"{pair}_metadata.json"),
        }

    @classmethod
    def create_directories(cls) -> None:
        """Create all output directories."""
        for d in [
            cls.PROCESSED_DATA_DIR,
            cls.MODEL_DIR,
            cls.LOGS_DIR,
        ]:
            Path(d).mkdir(parents=True, exist_ok=True)
