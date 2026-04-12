"""Technical indicator calculations for OHLCV data."""

import numpy as np
import pandas as pd
import talib
from numpy.typing import ArrayLike


def obv_momentum(close: ArrayLike, volume: ArrayLike) -> dict[str, np.ndarray]:
    """Calculate On-Balance Volume momentum indicators.

    Args:
        close: Array of closing prices.
        volume: Array of volumes.

    Returns:
        Dictionary with AOBV linear regression slope and rate of change.
    """
    obv = talib.OBV(close, volume)  # type: ignore
    return {
        "AOBV_LR_2": talib.LINEARREG_SLOPE(obv, timeperiod=2),
        "AOBV_SR_2": talib.ROC(obv, timeperiod=2),
    }


def price_volume_ratio(
    open_: ArrayLike, close: ArrayLike, volume: ArrayLike, index: pd.Index
) -> dict[str, pd.Series]:
    """Calculate normalized price-volume ratio indicator.

    Args:
        open_: Array of opening prices.
        close: Array of closing prices.
        volume: Array of volumes.
        index: Index for the resulting Series.

    Returns:
        Dictionary with normalized price-volume ratio.
    """
    pv = pd.Series((close - open_) * volume, index=index)  # type: ignore
    pvr = (pv - pv.rolling(14, min_periods=1).mean()) / (
        pv.rolling(14, min_periods=1).std() + 1e-10
    )
    return {"PVR": pvr}


def trend_momentum(close: ArrayLike) -> dict[str, np.ndarray]:
    """Calculate trend momentum indicator.

    Args:
        close: Array of closing prices.

    Returns:
        Dictionary with 6-period EMA momentum.
    """
    return {"TTM_TRND_6": talib.MOM(talib.EMA(close, timeperiod=6), timeperiod=1)}  # type: ignore


def macd(close: ArrayLike) -> dict[str, np.ndarray]:
    """Calculate MACD (Moving Average Convergence Divergence) line.

    Args:
        close: Array of closing prices.

    Returns:
        Dictionary with 12/26/9 MACD line.
    """
    value, _, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)  # type: ignore
    return {"MACD_12_26_9": value}


def rsi(close: ArrayLike) -> dict[str, np.ndarray]:
    """Calculate Relative Strength Index indicator.

    Args:
        close: Array of closing prices.

    Returns:
        Dictionary with 14-period RSI.
    """
    return {"RSI_14": talib.RSI(close, timeperiod=14)}  # type: ignore


def adx(high: ArrayLike, low: ArrayLike, close: ArrayLike) -> dict[str, np.ndarray]:
    """Calculate Average Directional Index indicator.

    Args:
        high: Array of high prices.
        low: Array of low prices.
        close: Array of closing prices.

    Returns:
        Dictionary with 14-period ADX.
    """
    return {"ADX_14": talib.ADX(high, low, close, timeperiod=14)}  # type: ignore


def stoch_rsi(close: ArrayLike, index: pd.Index) -> dict[str, pd.Series]:
    """Calculate Stochastic RSI (K-line) indicator.

    Args:
        close: Array of closing prices.
        index: Index for the resulting Series.

    Returns:
        Dictionary with 10/14/3/3 Stochastic RSI K-line.
    """
    rsi_vals = pd.Series(talib.RSI(close, timeperiod=14), index=index)  # type: ignore
    lo = rsi_vals.rolling(14, min_periods=14).min()
    hi = rsi_vals.rolling(14, min_periods=14).max()
    smoothed = ((rsi_vals - lo) / (hi - lo + 1e-10)).rolling(3, min_periods=1).mean()
    return {"STOCHRSIk_10_14_3_3": smoothed}


def direction_flags(close: ArrayLike) -> dict[str, np.ndarray]:
    """Calculate price direction flags (up/down).

    Args:
        close: Array of closing prices.

    Returns:
        Dictionary with binary up and down direction flags.
    """
    inc = (close > np.roll(close, 1)).astype(int)
    dec = (close < np.roll(close, 1)).astype(int)
    inc[0] = 0
    dec[0] = 0
    return {"INC_1": inc, "DEC_1": dec}


def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators and append to DataFrame.

    Each indicator is computed separately so failures can be pinpointed by name.
    OHLCV columns are normalized to float64 before computation.

    Args:
        data: DataFrame with OHLCV columns.

    Returns:
        DataFrame with all computed indicator columns appended.

    Raises:
        RuntimeError: If any indicator calculation fails.
    """
    df = data.copy()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)  # type: ignore

    o, h, lo, c, v = (df[k].values for k in ["Open", "High", "Low", "Close", "Volume"])
    idx = df.index

    groups = [
        ("OBV momentum", lambda: obv_momentum(c, v)),  # type: ignore
        ("price-volume ratio", lambda: price_volume_ratio(o, c, v, idx)),  # type: ignore
        ("trend momentum", lambda: trend_momentum(c)),  # type: ignore
        ("MACD", lambda: macd(c)),  # type: ignore
        ("RSI", lambda: rsi(c)),  # type: ignore
        ("ADX", lambda: adx(h, lo, c)),  # type: ignore
        ("Stochastic RSI", lambda: stoch_rsi(c, idx)),  # type: ignore
        ("direction flags", lambda: direction_flags(c)),  # type: ignore
    ]

    for name, fn in groups:
        try:
            for col_name, values in fn().items():
                df[col_name] = values
        except Exception as e:
            raise RuntimeError(f"Failed computing {name}: {e}") from e

    return df
