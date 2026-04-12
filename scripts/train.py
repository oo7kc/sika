"""Training pipeline for fitting ML models on historical data."""

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import MinMaxScaler

from config import Config
from scripts.data import is_crypto, load_data, prepare_features_target
from scripts.indicators import calculate_indicators
from scripts.logger import get_logger

logger = get_logger(__name__)


class TrainingPipeline:
    """Pipeline for training and saving ML models on trading data.

    Loads historical OHLCV data, computes technical indicators, prepares
    features and targets, trains an MLPClassifier, and saves all artifacts.
    """

    def __init__(self, pair: str | None = None) -> None:
        """Initialize the training pipeline for a trading pair.

        Args:
            pair: Trading pair symbol (e.g., "XAUUSD"). If None, uses the
                first pair from configuration.
        """
        self.config = Config()
        self.pair = (pair or self.config.TRADING_PAIRS[0]).upper()
        self.paths = self.config.get_paths(self.pair)
        self.scaler: MinMaxScaler | None = None
        self.model: MLPClassifier | None = None
        self.metrics: dict = {}

    def load_and_preprocess(self) -> tuple[pd.DataFrame, pd.Series]:
        """Load raw data, compute indicators, and prepare features.

        Returns:
            Tuple of (X, y) where X is features and y is the Gamma target labels.

        Raises:
            FileNotFoundError: If raw data file doesn't exist.
            ValueError: If data is insufficient after preprocessing.
        """
        logger.info(f"Loading data for {self.pair}")
        data = load_data(
            self.paths["raw_data"], exclude_weekends=not is_crypto(self.pair)
        )
        logger.info("Computing indicators")
        data = calculate_indicators(data)
        logger.info("Preparing features and target")
        return prepare_features_target(
            data, self.config.SELECTED_FEATURES, self.config.START_DATE
        )

    def fit(self, X: pd.DataFrame, y: pd.Series) -> dict[str, object]:
        """Scale features, build, and train the MLPClassifier model.

        Performs a chronological 80/20 train/test split, fits the scaler on
        training data, and trains the model. Computes accuracy metrics on both
        splits.

        Args:
            X: Feature matrix.
            y: Target labels.

        Returns:
            Metadata dictionary with model architecture and training metrics.

        Raises:
            ValueError: If fewer than 10 rows available after preprocessing.
        """
        if len(X) < 10:
            raise ValueError(
                f"Not enough rows to train {self.pair}. "
                "Need at least 10 after preprocessing."
            )

        split_idx = max(int(len(X) * 0.8), 1)
        if split_idx >= len(X):
            split_idx = len(X) - 1

        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        logger.info(
            f"Chronological split — train={len(X_train)} rows, test={len(X_test)} rows"
        )
        logger.info("Fitting MinMaxScaler on training split")
        self.scaler = MinMaxScaler()
        X_train_scaled = pd.DataFrame(
            self.scaler.fit_transform(X_train),
            columns=X_train.columns,
            index=X_train.index,
        )
        X_test_scaled = pd.DataFrame(
            self.scaler.transform(X_test), columns=X_test.columns, index=X_test.index
        )

        n_features = X_train_scaled.shape[1]
        n_classes = len(np.unique(y))
        hidden_size = (n_features + n_classes) // 2

        logger.info(f"Building MLPClassifier — hidden_size={hidden_size}")
        self.model = MLPClassifier(
            hidden_layer_sizes=(hidden_size,),
            activation=self.config.ACTIVATION,
            solver=self.config.SOLVER,
            learning_rate=self.config.LEARNING_RATE,
            learning_rate_init=self.config.LEARNING_RATE_INIT,
            max_iter=self.config.MAX_ITER,
            momentum=self.config.MOMENTUM,
            random_state=self.config.RANDOM_STATE,
            early_stopping=self.config.EARLY_STOPPING,
        )

        logger.info("Training model")
        self.model.fit(X_train_scaled, y_train)
        logger.info(f"Training complete — loss: {self.model.loss_:.6f}")

        train_accuracy = accuracy_score(y_train, self.model.predict(X_train_scaled))
        test_accuracy = accuracy_score(y_test, self.model.predict(X_test_scaled))
        self.metrics = {
            "train_rows": len(X_train),
            "test_rows": len(X_test),
            "train_accuracy": train_accuracy,
            "test_accuracy": test_accuracy,
        }
        logger.info(
            f"Accuracy — train: {train_accuracy:.2%} | holdout: {test_accuracy:.2%}"
        )

        return {
            "pair": self.pair,
            "n_features": n_features,
            "n_classes": n_classes,
            "hidden_layer_size": hidden_size,
            "feature_names": self.config.SELECTED_FEATURES,
            "metrics": self.metrics,
        }

    def save(self, metadata: dict[str, object]) -> None:
        """Save trained model, scaler, and metadata to disk.

        Args:
            metadata: Dictionary with model architecture and training metrics.

        Raises:
            IOError: If files cannot be written.
        """
        self.config.create_directories()
        joblib.dump(self.model, self.paths["model"])
        logger.info(f"Model  → {self.paths['model']}")
        joblib.dump(self.scaler, self.paths["scaler"])
        logger.info(f"Scaler → {self.paths['scaler']}")
        with open(self.paths["metadata"], "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Meta   → {self.paths['metadata']}")

    def run(self) -> None:
        """Execute the complete training pipeline.

        Loads data, preprocesses, trains model, saves all artifacts.

        Raises:
            FileNotFoundError: If raw data doesn't exist.
            ValueError: If insufficient data for training.
            IOError: If artifacts cannot be saved.
        """
        logger.info(f"=== Training start: {self.pair} ===")
        X, y = self.load_and_preprocess()
        metadata = self.fit(X, y)
        self.save(metadata)
        logger.info(f"=== Training done:  {self.pair} ===")


if __name__ == "__main__":
    TrainingPipeline().run()
