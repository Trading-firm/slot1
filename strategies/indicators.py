"""
strategies/indicators.py
─────────────────────────
All technical indicators used across strategies.
"""

import pandas as pd
import numpy as np


def calc_ema(df: pd.DataFrame, span: int) -> pd.Series:
    return df["Close"].ewm(span=span, adjust=False).mean()


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    # When loss == 0 (no down-moves in the period), RSI should be 100.
    # Replace 0 in the denominator with NaN so the division yields inf,
    # then use clip to cap RSI at 100 without producing NaN.
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100)  # flat/pure-up market → RSI = 100


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates the Average Directional Index (ADX)."""
    plus_dm = df["High"].diff()
    minus_dm = df["Low"].diff()
    
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    minus_dm = minus_dm.abs()
    
    atr = calc_atr(df, period)
    
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(period).mean()
    
    return adx


def calc_supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    atr_s = calc_atr(df, period)
    hl2   = (df["High"] + df["Low"]) / 2
    upper = hl2 + mult * atr_s
    lower = hl2 - mult * atr_s

    upper = upper.copy()
    lower = lower.copy()
    trend = [True] * len(df)

    for i in range(1, len(df)):
        if df["Close"].iloc[i] > upper.iloc[i-1]:
            trend[i] = True
        elif df["Close"].iloc[i] < lower.iloc[i-1]:
            trend[i] = False
        else:
            trend[i] = trend[i-1]
            if trend[i] and lower.iloc[i] < lower.iloc[i-1]:
                lower.iloc[i] = lower.iloc[i-1]
            if not trend[i] and upper.iloc[i] > upper.iloc[i-1]:
                upper.iloc[i] = upper.iloc[i-1]

    return pd.Series(trend, index=df.index)


def calc_bollinger_bands(df: pd.DataFrame, period=20, std_dev=2.0) -> (pd.Series, pd.Series):
    """Calculates the upper and lower Bollinger Bands."""
    sma = df['Close'].rolling(window=period).mean()
    std = df['Close'].rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return upper_band, lower_band


def calc_keltner_channels(df: pd.DataFrame, period=20, atr_mult=1.5) -> (pd.Series, pd.Series):
    """Calculates the upper and lower Keltner Channels."""
    ema = calc_ema(df, period)
    atr = calc_atr(df, period)
    upper_channel = ema + (atr * atr_mult)
    lower_channel = ema - (atr * atr_mult)
    return upper_channel, lower_channel


def calc_fvg(df: pd.DataFrame):
    """
    Identifies Fair Value Gaps (FVG).
    Returns a Series of FVG objects or None.
    """
    fvgs = [None] * len(df)
    for i in range(2, len(df)):
        # Bullish FVG (Gap between Low of candle i and High of candle i-2)
        if df["Low"].iloc[i] > df["High"].iloc[i-2]:
            fvgs[i] = {"type": "BULLISH", "top": df["Low"].iloc[i], "bottom": df["High"].iloc[i-2]}
        # Bearish FVG (Gap between High of candle i and Low of candle i-2)
        elif df["High"].iloc[i] < df["Low"].iloc[i-2]:
            fvgs[i] = {"type": "BEARISH", "top": df["Low"].iloc[i-2], "bottom": df["High"].iloc[i]}
    return fvgs


def calc_order_blocks(df: pd.DataFrame, lookback: int = 200):
    """
    Identifies Order Blocks (OB) more efficiently.
    Returns a list of OBs.
    """
    obs = []
    # Vectorized condition for strong move up/down
    high_max = df["High"].rolling(window=5).max().shift(1)
    low_min = df["Low"].rolling(window=5).min().shift(1)
    
    strong_up = df["Close"] > high_max
    strong_down = df["Close"] < low_min
    
    # Only check recent strong moves to speed up
    indices = df.index[strong_up | strong_down]
    # Limit to the last few hundred bars if needed, but let's try this
    
    for i in range(len(df)-lookback, len(df)):
        if strong_up.iloc[i]:
            for j in range(i-1, i-10, -1):
                if df["Close"].iloc[j] < df["Open"].iloc[j]:
                    obs.append({"type": "BULLISH", "top": df["High"].iloc[j], "bottom": df["Low"].iloc[j], "index": j})
                    break
        elif strong_down.iloc[i]:
            for j in range(i-1, i-10, -1):
                if df["Close"].iloc[j] > df["Open"].iloc[j]:
                    obs.append({"type": "BEARISH", "top": df["High"].iloc[j], "bottom": df["Low"].iloc[j], "index": j})
                    break
    return obs


def calc_liquidity_levels(df: pd.DataFrame, window: int = 20):
    """
    Identifies key liquidity zones (Recent Highs/Lows).
    """
    # Recent peaks and troughs
    resistance = df["High"].rolling(window=window).max()
    support    = df["Low"].rolling(window=window).min()
    return resistance, support


def calc_swing_points(df: pd.DataFrame, window: int = 14):
    """
    Extract swing highs and lows for structural support/resistance.
    Used for determining SL/TP levels.
    """
    highs = []
    lows = []
    
    for i in range(len(df)):
        if i < window:
            highs.append(df["High"].iloc[0:i+1].max())
            lows.append(df["Low"].iloc[0:i+1].min())
        else:
            highs.append(df["High"].iloc[i-window:i+1].max())
            lows.append(df["Low"].iloc[i-window:i+1].min())
    
    return pd.Series(highs, index=df.index), pd.Series(lows, index=df.index)
