"""Data loading and feature preparation."""

import numpy as np
import pandas as pd


def load_data(file_path: str, exclude_weekends: bool = True) -> pd.DataFrame:
    """Load OHLCV data from CSV with normalized datetime index."""
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
    start_date: str = "2020-01-01",
) -> tuple[pd.DataFrame, pd.Series]:
    """Build features and Gamma target label (sign of Close - Open)."""
    df = data.copy()
    df["Gamma"] = np.sign(df["Close"] - df["Open"])

    if start_date:
        df = df[df.index >= start_date]

    df = df.dropna()
    return df[selected_features], df["Gamma"]  # type: ignore


def is_crypto(pair: str) -> bool:
    return any(token in pair.upper() for token in ("BTC", "ETH", "SOL", "XRP"))
