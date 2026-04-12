"""Data loading and feature preparation for model training and prediction."""

import numpy as np
import pandas as pd


def load_data(
    file_path: str,
    exclude_weekends: bool = True,
) -> pd.DataFrame:
    """Load OHLCV data from CSV and normalize the datetime index.

    Handles mixed datetime formats and sorts by date. Optionally excludes
    weekends for forex pairs (weekend rows are typically empty anyway).

    Args:
        file_path: Path to the CSV file containing OHLCV data.
        exclude_weekends: If True, removes Saturday/Sunday rows.
            Set to False for crypto pairs that trade 24/7.

    Returns:
        DataFrame with datetime index sorted chronologically.
        Columns include Open, High, Low, Close, Volume.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If no valid datetime column can be identified.
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
        df = df[~df.index.day_of_week.isin([5, 6])]  # type: ignore

    return df.sort_index()  # type: ignore


def prepare_features_target(
    data: pd.DataFrame,
    selected_features: list[str],
    start_date: str | None = "2020-01-01",
) -> tuple[pd.DataFrame, pd.Series]:
    """Slice features and build the Gamma target label.

    The target is computed as np.sign(Close - Open), producing {-1, 0, 1}
    labels representing down, neutral, and up days. Features are lagged by
    one bar to prevent lookahead bias.

    Args:
        data: DataFrame with indicator columns already computed.
        selected_features: Column names to use as model input features.
        start_date: Drop rows before this date (ISO format).
            If None, no date filtering is applied.

    Returns:
        Tuple of (X, y) where:
            - X is DataFrame of selected features
            - y is Series of Gamma target labels in {-1, 0, 1}

    Raises:
        KeyError: If any selected feature is missing from data.
        ValueError: If data is empty after preparation.
    """
    df = data.copy()
    df["Gamma"] = np.sign(df["Close"] - df["Open"])
    df[selected_features] = df[selected_features].shift(1)

    if start_date:
        df = df[df.index >= start_date]

    df = df.dropna()
    return df[selected_features], df["Gamma"]  # type: ignore


def is_crypto(pair: str) -> bool:
    """Check if a trading pair is cryptocurrency.

    Crypto pairs trade 24/7 including weekends, unlike forex pairs
    which are closed on weekends.

    Args:
        pair: Trading pair symbol (e.g., "BTCUSD", "XAUUSD").

    Returns:
        True if pair is a known crypto token, False otherwise.
    """
    return any(token in pair.upper() for token in ("BTC", "ETH", "SOL", "XRP"))
