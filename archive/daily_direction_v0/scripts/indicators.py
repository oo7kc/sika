"""Technical indicator calculations."""

from typing import Any

import numpy as np
import pandas as pd
import talib
from numpy.typing import NDArray


def obv_momentum(close: NDArray, volume: NDArray) -> dict[str, Any]:
    obv = talib.OBV(close, volume)
    return {
        "AOBV_LR_2": talib.LINEARREG_SLOPE(obv, timeperiod=2),
        "AOBV_SR_2": talib.ROC(obv, timeperiod=2),
    }


def price_volume_ratio(
    open_: NDArray, close: NDArray, volume: NDArray, index: Any
) -> dict[str, Any]:
    pv = pd.Series((close - open_) * volume, index=index)
    pvr = (pv - pv.rolling(14, min_periods=1).mean()) / (
        pv.rolling(14, min_periods=1).std() + 1e-10
    )
    return {"PVR": pvr}


def trend_momentum(close: NDArray) -> dict[str, Any]:
    return {"TTM_TRND_6": talib.MOM(talib.EMA(close, timeperiod=6), timeperiod=1)}


def macd(close: NDArray) -> dict[str, Any]:
    value, _, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    return {"MACD_12_26_9": value}


def rsi(close: NDArray) -> dict[str, Any]:
    return {"RSI_14": talib.RSI(close, timeperiod=14)}


def adx(high: NDArray, low_val: NDArray, close: NDArray) -> dict[str, Any]:
    return {"ADX_14": talib.ADX(high, low_val, close, timeperiod=14)}


def stoch_rsi(close: NDArray, index: Any) -> dict[str, Any]:
    rsi_vals = pd.Series(talib.RSI(close, timeperiod=14), index=index)
    lo = rsi_vals.rolling(14, min_periods=14).min()
    hi = rsi_vals.rolling(14, min_periods=14).max()
    smoothed = ((rsi_vals - lo) / (hi - lo + 1e-10)).rolling(3, min_periods=1).mean()
    return {"STOCHRSIk_10_14_3_3": smoothed}


def direction_flags(close: NDArray) -> dict[str, Any]:
    close_arr = np.asarray(close, dtype=np.float64)
    inc = (close_arr > np.roll(close_arr, 1)).astype(int)
    dec = (close_arr < np.roll(close_arr, 1)).astype(int)
    inc[0] = 0
    dec[0] = 0
    return {"INC_1": inc, "DEC_1": dec}


def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)

    open_, high, low_val, close, volume = (
        df[k].values for k in ["Open", "High", "Low", "Close", "Volume"]
    )
    idx = df.index

    groups = [
        ("OBV momentum", lambda: obv_momentum(close, volume)),
        (
            "price-volume ratio",
            lambda: price_volume_ratio(open_, close, volume, idx),
        ),
        ("trend momentum", lambda: trend_momentum(close)),
        ("MACD", lambda: macd(close)),
        ("RSI", lambda: rsi(close)),
        ("ADX", lambda: adx(high, low_val, close)),
        ("Stochastic RSI", lambda: stoch_rsi(close, idx)),
        ("direction flags", lambda: direction_flags(close)),
    ]

    for name, fn in groups:
        try:
            for col_name, values in fn().items():
                df[col_name] = values
        except Exception as e:
            raise RuntimeError(f"Failed computing {name}: {e}") from e

    return df
