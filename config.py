"""Central configuration management for the FX Trading ML Pipeline.

All configuration values are loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Central configuration for all pipeline settings.

    Loads configuration from environment variables with built-in defaults.
    Covers directories, trading pairs, data sources, and ML hyperparameters.

    All values can be overridden by setting environment variables, allowing
    flexibility across different deployment environments.
    """

    RAW_DATA_DIR: str = os.getenv("RAW_DATA_DIR", "data/raw")
    PROCESSED_DATA_DIR: str = os.getenv("PROCESSED_DATA_DIR", "data/processed")
    MODEL_DIR: str = os.getenv("MODEL_DIR", "models")
    REPORTS_DIR: str = os.getenv("REPORTS_DIR", "reports")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

    TRADING_PAIRS: list[str] = [
        p.strip() for p in os.getenv("TRADING_PAIRS", "XAUUSD").split(",")
    ]

    START_DATE: str = os.getenv("START_DATE", "2020-01-01")
    TIINGO_KEY: str = os.getenv("TIINGO_KEY", "").strip().strip('"').strip("'")

    RANDOM_STATE: int = int(os.getenv("RANDOM_STATE", "42"))
    ACTIVATION: str = os.getenv("ACTIVATION", "logistic")
    SOLVER: str = os.getenv("SOLVER", "lbfgs")
    LEARNING_RATE: str = os.getenv("LEARNING_RATE", "adaptive")
    LEARNING_RATE_INIT: float = float(os.getenv("LEARNING_RATE_INIT", "0.03"))
    MAX_ITER: int = int(os.getenv("MAX_ITER", "10000"))
    MOMENTUM: float = float(os.getenv("MOMENTUM", "0.2"))
    EARLY_STOPPING: bool = os.getenv("EARLY_STOPPING", "True").lower() == "true"

    SELECTED_FEATURES: list[str] = [
        f.strip()
        for f in os.getenv(
            "SELECTED_FEATURES",
            "AOBV_LR_2,AOBV_SR_2,PVR,TTM_TRND_6,MACD_12_26_9,RSI_14,ADX_14,"
            "STOCHRSIk_10_14_3_3,INC_1,DEC_1",
        ).split(",")
    ]

    @classmethod
    def get_paths(cls, pair: str) -> dict[str, str]:
        """Get all artifact and data file paths for a trading pair.

        Constructs standardized file paths for model artifacts, raw data,
        and prediction logs for a specific trading pair.

        Args:
            pair: Trading pair symbol (e.g., "XAUUSD").

        Returns:
            Dictionary with standardized paths:
                - raw_data: Path to raw OHLCV CSV file
                - model: Path to trained MLPClassifier pickle file
                - scaler: Path to MinMaxScaler pickle file
                - metadata: Path to JSON metadata file
                - log: Path to prediction log CSV file
        """
        pair = pair.upper()
        return {
            "raw_data": os.path.join(cls.RAW_DATA_DIR, f"{pair}RAW.csv"),
            "model": os.path.join(cls.MODEL_DIR, f"{pair}_mlp_classifier.pkl"),
            "scaler": os.path.join(cls.MODEL_DIR, f"{pair}_scaler.pkl"),
            "metadata": os.path.join(cls.MODEL_DIR, f"{pair}_metadata.json"),
            "log": os.path.join(cls.REPORTS_DIR, f"{pair.lower()}_prediction_log.csv"),
        }

    @classmethod
    def create_directories(cls) -> None:
        """Create all output directories if they don't exist.

        Ensures that all configured output directories exist before writing
        files to them. Creates parent directories as needed.
        """
        for d in [cls.PROCESSED_DATA_DIR, cls.MODEL_DIR, cls.REPORTS_DIR, cls.LOG_DIR]:
            Path(d).mkdir(parents=True, exist_ok=True)
