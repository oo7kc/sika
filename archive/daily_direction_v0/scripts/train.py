"""Training pipeline — chronological split, leak-free scaling, accuracy metrics."""

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

_MIN_ROWS = 20


class TrainingPipeline:
    """Train MLP classifier on forex pairs with chronological split."""

    def __init__(self, pair: str | None = None) -> None:
        self.config = Config()
        self.pair = (pair or self.config.TRADING_PAIRS[0]).upper()
        self.paths = self.config.get_paths(self.pair)
        self.scaler: MinMaxScaler | None = None
        self.model: MLPClassifier | None = None

    def load_and_preprocess(self) -> tuple[pd.DataFrame, pd.Series]:
        """Load raw data and calculate indicators."""
        data = load_data(
            self.paths["raw_data"], exclude_weekends=not is_crypto(self.pair)
        )
        data = calculate_indicators(data)
        X, y = prepare_features_target(
            data, self.config.SELECTED_FEATURES, self.config.START_DATE
        )
        logger.info(f"Dataset ready — {len(X)} rows, {X.shape[1]} features")
        return X, y

    def _split(
        self, X: pd.DataFrame, y: pd.Series
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """Chronological train/test split — no shuffling, no future leakage.

        Uses TRAIN_SPLIT from config (default 0.8). Validates that both splits
        have enough rows and that all target classes appear in training data.
        """
        if len(X) < _MIN_ROWS:
            raise ValueError(
                f"Only {len(X)} rows after preprocessing — need at least "
                f"{_MIN_ROWS}. Extend your date range or check the raw data file."
            )

        split_idx = int(len(X) * self.config.TRAIN_SPLIT)
        split_idx = max(1, min(split_idx, len(X) - 1))

        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        missing = set(y_test.unique()) - set(y_train.unique())
        if missing:
            logger.warning(
                f"Class(es) {missing} appear in test but not in training split. "
                "Model will never predict them — consider a wider date range."
            )

        logger.info(
            f"Split — train: {len(X_train)} rows "
            f"({X_train.index[0].date()} → {X_train.index[-1].date()}), "
            f"test: {len(X_test)} rows "
            f"({X_test.index[0].date()} → {X_test.index[-1].date()})"
        )
        _log_class_distribution("train", y_train)
        _log_class_distribution("test", y_test)

        return X_train, X_test, y_train, y_test

    def fit(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """Scale, build, train. Scaler fit on train only — no leakage."""
        X_train, X_test, y_train, y_test = self._split(X, y)

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

        self.model.fit(X_train_scaled, y_train)

        train_acc = accuracy_score(y_train, self.model.predict(X_train_scaled))
        test_acc = accuracy_score(y_test, self.model.predict(X_test_scaled))
        logger.info(f"Accuracy — train: {train_acc:.2%} | holdout: {test_acc:.2%}")

        return {
            "pair": self.pair,
            "n_features": n_features,
            "n_classes": n_classes,
            "hidden_layer_size": hidden_size,
            "feature_names": self.config.SELECTED_FEATURES,
            "train_split": self.config.TRAIN_SPLIT,
            "metrics": {
                "train_rows": len(X_train),
                "test_rows": len(X_test),
                "train_accuracy": round(train_acc, 4),
                "test_accuracy": round(test_acc, 4),
            },
        }

    def save(self, metadata: dict) -> None:
        """Save model, scaler, and metadata to disk."""
        self.config.create_directories()
        joblib.dump(self.model, self.paths["model"])
        logger.info(f"Model  → {self.paths['model']}")
        joblib.dump(self.scaler, self.paths["scaler"])
        logger.info(f"Scaler → {self.paths['scaler']}")
        with open(self.paths["metadata"], "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Meta   → {self.paths['metadata']}")

    def run(self) -> dict:
        """Run full pipeline and return the metadata/metrics dict."""
        logger.info(f"=== Training start: {self.pair} ===")
        X, y = self.load_and_preprocess()
        metadata = self.fit(X, y)
        self.save(metadata)
        logger.info(f"=== Training done:  {self.pair} ===")
        return metadata


def _log_class_distribution(label: str, y: pd.Series) -> None:
    """Log the count and percentage of each class in a split."""
    counts = y.value_counts().sort_index()
    parts = [f"{cls}: {n} ({n / len(y):.0%})" for cls, n in counts.items()]
    logger.info(f"Class distribution [{label}] — {', '.join(parts)}")


if __name__ == "__main__":
    TrainingPipeline().run()
