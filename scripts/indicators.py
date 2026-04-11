"""Technical indicator calculations.

Each indicator group is its own function so a failure pinpoints exactly
what broke. ``calculate_indicators`` assembles them all.
"""

import numpy as np
import pandas as pd
import talib

# ---------------------------------------------------------------------------
# Individual indicator functions
# Each returns a dict {column_name: array_or_series}
# ---------------------------------------------------------------------------


def obv_momentum(close: np.ndarray, volume: np.ndarray) -> dict:
    obv = talib.OBV(close, volume)
    return {
        "AOBV_LR_2": talib.LINEARREG_SLOPE(obv, timeperiod=2),
        "AOBV_SR_2": talib.ROC(obv, timeperiod=2),
    }


def price_volume_ratio(
    open_: np.ndarray, close: np.ndarray, volume: np.ndarray, index
) -> dict:
    pv = pd.Series((close - open_) * volume, index=index)
    pvr = (pv - pv.rolling(14, min_periods=1).mean()) / (
        pv.rolling(14, min_periods=1).std() + 1e-10
    )
    return {"PVR": pvr}


def trend_momentum(close: np.ndarray) -> dict:
    return {"TTM_TRND_6": talib.MOM(talib.EMA(close, timeperiod=6), timeperiod=1)}


def macd(close: np.ndarray) -> dict:
    value, _, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    return {"MACD_12_26_9": value}


def rsi(close: np.ndarray) -> dict:
    return {"RSI_14": talib.RSI(close, timeperiod=14)}


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    return {"ADX_14": talib.ADX(high, low, close, timeperiod=14)}


def stoch_rsi(close: np.ndarray, index) -> dict:
    rsi_vals = pd.Series(talib.RSI(close, timeperiod=14), index=index)
    lo = rsi_vals.rolling(14, min_periods=14).min()
    hi = rsi_vals.rolling(14, min_periods=14).max()
    smoothed = ((rsi_vals - lo) / (hi - lo + 1e-10)).rolling(3, min_periods=1).mean()
    return {"STOCHRSIk_10_14_3_3": smoothed}


def direction_flags(close: np.ndarray) -> dict:
    inc = (close > np.roll(close, 1)).astype(int)
    dec = (close < np.roll(close, 1)).astype(int)
    inc[0] = 0
    dec[0] = 0
    return {"INC_1": inc, "DEC_1": dec}


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """Compute all features and append them to the DataFrame.

    Each group is called individually so failures are pinpointed by name.
    """
    df = data.copy()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)

    o, h, l, c, v = (df[k].values for k in ["Open", "High", "Low", "Close", "Volume"])
    idx = df.index

    groups = [
        ("OBV momentum", lambda: obv_momentum(c, v)),
        ("price-volume ratio", lambda: price_volume_ratio(o, c, v, idx)),
        ("trend momentum", lambda: trend_momentum(c)),
        ("MACD", lambda: macd(c)),
        ("RSI", lambda: rsi(c)),
        ("ADX", lambda: adx(h, l, c)),
        ("Stochastic RSI", lambda: stoch_rsi(c, idx)),
        ("direction flags", lambda: direction_flags(c)),
    ]

    for name, fn in groups:
        try:
            for col_name, values in fn().items():
                df[col_name] = values
        except Exception as e:
            raise RuntimeError(f"Failed computing {name}: {e}") from e

    return df
