"""Data loading and feature preparation."""

from typing import Tuple

import numpy as np
import pandas as pd


def load_data(file_path: str, exclude_weekends: bool = True) -> pd.DataFrame:
    """Load OHLCV data from CSV and normalise the datetime index.

    Args:
        file_path: Path to the CSV file.
        exclude_weekends: Drop Saturday/Sunday rows. Set False for crypto pairs.

    Returns:
        DataFrame sorted by datetime index.
    """
    df = pd.read_csv(file_path)

    dt_candidates = [c for c in df.columns if "gmt" in c.lower() or "time" in c.lower()]
    if dt_candidates:
        dt_col = dt_candidates[0]
        df[dt_col] = pd.to_datetime(df[dt_col], dayfirst=True, format="mixed")
        df = df.set_index(dt_col)
    else:
        df = pd.read_csv(file_path, index_col=0)
        df.index = pd.to_datetime(df.index, dayfirst=True, format="mixed")

    if exclude_weekends:
        df = df[~df.index.day_of_week.isin([5, 6])]

    return df.sort_index()


def prepare_features_target(
    data: pd.DataFrame,
    selected_features: list,
    start_date: str = "2020-01-01",
) -> Tuple[pd.DataFrame, pd.Series]:
    """Slice features and build the Gamma target label.

    Args:
        data: DataFrame with indicator columns already computed.
        selected_features: Column names to use as model input.
        start_date: Drop rows before this date.

    Returns:
        (X, y) where y = np.sign(Close - Open) in {-1, 0, 1}.
    """
    df = data.copy()
    df["Gamma"] = np.sign(df["Close"] - df["Open"])
    df[selected_features] = df[selected_features].shift(1)

    if start_date:
        df = df[df.index >= start_date]

    df = df.dropna()
    return df[selected_features], df["Gamma"]


def is_crypto(pair: str) -> bool:
    """Return True for pairs that trade on weekends."""
    return any(token in pair.upper() for token in ("BTC", "ETH", "SOL", "XRP"))
