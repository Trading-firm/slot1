"""
strategies/scalper.py
──────────────────────
Momentum Candle Scalper.

Entry rule (single completed candle):
  1. Body >= body_min_pct of total range (default 0.6)
  2. Body > average body of last N candles (default 5)
  3. Close in upper third (BUY) or lower third (SELL) of candle range
  4. Optional EMA8 alignment (close above EMA8 for BUY, below for SELL)
  5. Range >= min_range_x_spread × spread (skip if too small to scalp)

Exit:
  - SL = trigger candle's low/high ± buffer (structural stop)
  - TP = SL distance × rr_ratio (default 1.0 = 1:1)
"""
from dataclasses import dataclass
import math
import pandas as pd
from strategies.indicators import calc_ema, calc_atr


@dataclass
class ScalpSignal:
    direction: str    # "BUY" / "SELL" / "NONE"
    reason:    str
    entry:     float  # next-bar entry (estimated as current close)
    sl:        float
    tp:        float
    body_pct:  float  # for diagnostics


def generate_scalp_signal(
    df: pd.DataFrame,
    cfg: dict,
    spread_price: float = 0.0,
) -> ScalpSignal:
    """
    Evaluate the last *completed* candle (idx=-2) for a scalp setup.
    Returns ScalpSignal with direction == "NONE" if no setup.
    """
    f = cfg.get("filters", {})
    body_min_pct       = f.get("body_min_pct", 0.6)
    body_lookback      = f.get("body_lookback", 5)
    close_extremity    = f.get("close_extremity", 1/3)   # close within top/bottom 1/3
    min_range_x_spread = f.get("min_range_x_spread", 4)
    use_ema_filter     = f.get("use_ema_filter", True)
    ema_period         = f.get("ema_period", 8)
    sl_buffer_atr      = f.get("sl_buffer_atr", 0.1)
    rr_ratio           = f.get("rr_ratio", 1.0)
    atr_period         = f.get("atr_period", 14)

    if len(df) < max(body_lookback + 5, ema_period + 2, atr_period + 2):
        return ScalpSignal("NONE", "insufficient bars", 0, 0, 0, 0)

    idx = -2  # last completed candle
    o = df["Open"].iloc[idx]
    h = df["High"].iloc[idx]
    l = df["Low"].iloc[idx]
    c = df["Close"].iloc[idx]

    rng = h - l
    if rng <= 0:
        return ScalpSignal("NONE", "zero range", 0, 0, 0, 0)

    body = abs(c - o)
    body_pct = body / rng

    # Filter 1: body strength
    if body_pct < body_min_pct:
        return ScalpSignal("NONE", f"weak body {body_pct:.2f}", c, 0, 0, body_pct)

    # Filter 2: body larger than recent average
    bodies = (df["Close"] - df["Open"]).abs().iloc[idx - body_lookback : idx]
    avg_body = bodies.mean()
    if body <= avg_body:
        return ScalpSignal("NONE", "body not above avg", c, 0, 0, body_pct)

    # Filter 3: range big enough to be worth scalping (cover spread)
    if spread_price > 0 and rng < min_range_x_spread * spread_price:
        return ScalpSignal("NONE", f"range too small ({rng:.5f} < {min_range_x_spread}*spread)", c, 0, 0, body_pct)

    # Filter 4: close in extremity
    upper_cutoff = h - rng * close_extremity     # close must be ABOVE this for BUY
    lower_cutoff = l + rng * close_extremity     # close must be BELOW this for SELL

    # Filter 5: EMA8 alignment (optional)
    if use_ema_filter:
        ema = calc_ema(df, ema_period).iloc[idx]
        if math.isnan(ema):
            return ScalpSignal("NONE", "ema not ready", c, 0, 0, body_pct)
    else:
        ema = None

    atr = calc_atr(df, atr_period).iloc[idx]
    if math.isnan(atr):
        return ScalpSignal("NONE", "atr not ready", c, 0, 0, body_pct)

    direction = "NONE"
    if c > o and c >= upper_cutoff and (ema is None or c > ema):
        direction = "BUY"
    elif c < o and c <= lower_cutoff and (ema is None or c < ema):
        direction = "SELL"
    else:
        return ScalpSignal("NONE", "direction filter failed", c, 0, 0, body_pct)

    # Structural SL with small ATR buffer
    buffer = atr * sl_buffer_atr
    if direction == "BUY":
        sl = l - buffer
        sl_dist = c - sl
        if sl_dist <= 0:
            return ScalpSignal("NONE", "sl_dist <= 0", c, 0, 0, body_pct)
        tp = c + sl_dist * rr_ratio
    else:
        sl = h + buffer
        sl_dist = sl - c
        if sl_dist <= 0:
            return ScalpSignal("NONE", "sl_dist <= 0", c, 0, 0, body_pct)
        tp = c - sl_dist * rr_ratio

    return ScalpSignal(
        direction=direction,
        reason=f"momentum candle body={body_pct:.2f} range={rng:.5f}",
        entry=c,
        sl=sl,
        tp=tp,
        body_pct=body_pct,
    )