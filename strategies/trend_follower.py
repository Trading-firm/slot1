"""
strategies/trend_follower.py
─────────────────────────────
EMA trend-following entry with candlestick pattern confirmation.

Logic (per "The Candlestick Trading Bible"):
  1. Trend filter (M15): close vs EMA200
       close > EMA200 + chop_buf → UPTREND  (BUY only)
       close < EMA200 - chop_buf → DOWNTREND (SELL only)
       within ±chop_buf of EMA200 → no trade (chop zone, undefined trend)
  2. Pullback: in the last N bars, price's low (BUY) or high (SELL)
     touched/crossed EMA50. This means we're not chasing — we're entering
     after a retracement, at the start of a likely impulsive move.
  3. Entry trigger: a directional candlestick pattern fires on the entry bar
     in the trend direction (hammer/bullish_engulfing for BUY, etc.).
  4. SL: just beyond pattern bar's wick + sl_buffer_atr * ATR.
  5. TP: entry +/- min_rr * SL_dist.

The pattern bar = last CLOSED bar (`-2` in live where -1 is in-progress;
`-1` in backtest slices that don't carry an in-progress bar). Caller picks.

Run `python strategies/trend_follower.py` to execute self-tests.
"""
from dataclasses import dataclass
from typing import Optional, List
import pandas as pd

from strategies.indicators import calc_ema, calc_atr
from strategies.candlestick_patterns import detect_patterns, DIR_BUY, DIR_SELL


@dataclass
class TrendSetup:
    direction:    str       # "BUY" or "SELL"
    entry_price:  float     # last closed bar's close
    sl:           float
    tp:           float
    pattern:      str       # pattern name that confirmed entry
    atr:          float     # ATR at entry — useful for trailing/BE later
    ema_trend:    float     # EMA200 value at entry — used for trend-flip exit
    reason:       str


DEFAULT_PATTERNS = [
    "hammer", "shooting_star",
    "bullish_engulfing", "bearish_engulfing",
]


def find_entry(
    df: pd.DataFrame,
    cfg: dict,
    bar_idx: int = -2,
) -> Optional[TrendSetup]:
    """
    Returns a TrendSetup if all gates pass on `bar_idx`, else None.
    Caller handles the bar_idx convention (live = -2, backtest slice = -1).
    """
    # Normalize index to positive
    n = len(df)
    if bar_idx < 0:
        bar_idx = n + bar_idx
    if bar_idx < 0 or bar_idx >= n:
        return None

    ema_trend_period    = cfg.get("ema_trend",          200)
    ema_pullback_period = cfg.get("ema_pullback",       50)
    pullback_lookback   = cfg.get("pullback_lookback",  6)
    chop_band_atr       = cfg.get("chop_band_atr",      0.5)
    min_rr              = cfg.get("min_rr",             2.0)
    sl_buffer_atr       = cfg.get("sl_buffer_atr",      0.3)
    min_sl_atr          = cfg.get("min_sl_atr",         0.3)
    required_pattern    = cfg.get("required_pattern",   DEFAULT_PATTERNS)
    sessions            = cfg.get("sessions",           [])

    # Need EMA-trend warmup
    if bar_idx < ema_trend_period:
        return None

    ema_t_series = calc_ema(df, ema_trend_period)
    ema_p_series = calc_ema(df, ema_pullback_period)
    atr_series   = calc_atr(df, 14)

    ema_t = float(ema_t_series.iloc[bar_idx])
    ema_p = float(ema_p_series.iloc[bar_idx])
    atr   = float(atr_series.iloc[bar_idx])
    if pd.isna(ema_t) or pd.isna(ema_p) or pd.isna(atr) or atr <= 0:
        return None

    bar_high  = float(df["High"].iloc[bar_idx])
    bar_low   = float(df["Low"].iloc[bar_idx])
    bar_close = float(df["Close"].iloc[bar_idx])

    if sessions and "time" in df.columns:
        bar_time = df["time"].iloc[bar_idx]
        if not _in_session(bar_time, sessions):
            return None

    # ── Gate 1: trend direction ─────────────────────────────
    chop_buf = chop_band_atr * atr
    if bar_close > ema_t + chop_buf:
        trend_dir = DIR_BUY
    elif bar_close < ema_t - chop_buf:
        trend_dir = DIR_SELL
    else:
        return None

    # ── Gate 2: pullback to EMA50 within lookback ──────────
    start = max(0, bar_idx - pullback_lookback + 1)
    pulled_back = False
    for i in range(start, bar_idx + 1):
        ema_p_i = ema_p_series.iloc[i]
        if pd.isna(ema_p_i):
            continue
        low_i  = float(df["Low"].iloc[i])
        high_i = float(df["High"].iloc[i])
        if trend_dir == DIR_BUY and low_i <= ema_p_i:
            pulled_back = True
            break
        if trend_dir == DIR_SELL and high_i >= ema_p_i:
            pulled_back = True
            break

    if not pulled_back:
        return None

    # ── Gate 3: candlestick confirmation ────────────────────
    matches = detect_patterns(
        df, bar_idx=bar_idx,
        direction_filter=trend_dir,
        enabled=required_pattern,
    )
    if not matches:
        return None
    pattern = matches[0]

    # ── Build setup ─────────────────────────────────────────
    sl_buf = sl_buffer_atr * atr
    if trend_dir == DIR_BUY:
        sl = bar_low - sl_buf
        sl_dist = bar_close - sl
    else:
        sl = bar_high + sl_buf
        sl_dist = sl - bar_close

    if sl_dist <= 0 or sl_dist < min_sl_atr * atr:
        return None

    if trend_dir == DIR_BUY:
        tp = bar_close + sl_dist * min_rr
    else:
        tp = bar_close - sl_dist * min_rr

    return TrendSetup(
        direction=trend_dir,
        entry_price=bar_close,
        sl=sl,
        tp=tp,
        pattern=pattern.name,
        atr=atr,
        ema_trend=ema_t,
        reason=(f"{trend_dir} pullback to EMA{ema_pullback_period} "
                f"(close {bar_close:.5f} vs EMA200 {ema_t:.5f}); "
                f"confirmed by {pattern.name}"),
    )


def trend_flipped(df: pd.DataFrame, direction: str, ema_trend_period: int = 200,
                  bar_idx: int = -2, chop_band_atr: float = 0.5) -> bool:
    """
    True if the trade direction is now against the EMA200 trend (price closed
    on the wrong side, beyond the chop band). Use this for early-exit checks.
    """
    n = len(df)
    if bar_idx < 0:
        bar_idx = n + bar_idx
    if bar_idx < 0 or bar_idx >= n or bar_idx < ema_trend_period:
        return False
    ema_t = float(calc_ema(df, ema_trend_period).iloc[bar_idx])
    atr   = float(calc_atr(df, 14).iloc[bar_idx])
    if pd.isna(ema_t) or pd.isna(atr) or atr <= 0:
        return False
    close = float(df["Close"].iloc[bar_idx])
    chop_buf = chop_band_atr * atr
    if direction == DIR_BUY and close < ema_t - chop_buf:
        return True
    if direction == DIR_SELL and close > ema_t + chop_buf:
        return True
    return False


def _in_session(bar_time, sessions) -> bool:
    if not sessions:
        return True
    try:
        hour = int(bar_time.hour)
    except AttributeError:
        return True
    for sess in sessions:
        start, end = int(sess[0]), int(sess[1])
        if start <= end:
            if start <= hour < end:
                return True
        else:
            if hour >= start or hour < end:
                return True
    return False


# ── Self-tests ────────────────────────────────────────────────────────────────


def _make_synthetic_uptrend_with_pullback(n: int = 250) -> pd.DataFrame:
    """Generate a synthetic price series: long uptrend, then pullback to EMA50,
    then a hammer candle. Designed so find_entry should fire BUY on the last bar."""
    import numpy as np
    rng = np.random.default_rng(42)
    rows = []
    price = 100.0
    # First 200 bars: clean uptrend (drift up + small noise)
    for _ in range(200):
        drift = 0.20
        noise = rng.normal(0, 0.05)
        o = price
        c = price + drift + noise
        h = max(o, c) + abs(rng.normal(0, 0.05))
        l = min(o, c) - abs(rng.normal(0, 0.05))
        rows.append((o, h, l, c))
        price = c
    # Next 5 bars: pull back DOWN towards EMA50 (still above EMA200)
    for _ in range(5):
        o = price
        c = price - 0.30
        h = o + 0.05
        l = c - 0.05
        rows.append((o, h, l, c))
        price = c
    # Last 2 bars: small body, then a hammer (long lower wick, close back near top)
    o = price; c = price - 0.02; h = o + 0.05; l = c - 0.05
    rows.append((o, h, l, c)); price = c
    o = price
    c = price + 0.05    # small bullish body
    h = c + 0.02        # short upper shadow
    l = c - 0.80        # long lower shadow → hammer
    rows.append((o, h, l, c))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])


def _make_synthetic_choppy(n: int = 250) -> pd.DataFrame:
    """Sideways noise — should NOT fire any trade (close near EMA200)."""
    import numpy as np
    rng = np.random.default_rng(7)
    rows = []
    price = 100.0
    for _ in range(n):
        o = price
        c = price + rng.normal(0, 0.15)
        h = max(o, c) + abs(rng.normal(0, 0.10))
        l = min(o, c) - abs(rng.normal(0, 0.10))
        rows.append((o, h, l, c))
        price = c
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])


def _run_self_tests():
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  [OK]   {name}")
        else:
            failures.append(name)
            print(f"  [FAIL] {name}: {detail}")

    cfg = {
        "ema_trend": 50,           # smaller EMA for synthetic data
        "ema_pullback": 20,
        "pullback_lookback": 8,
        "chop_band_atr": 0.0,      # tight — synthetic data is clean
        "min_rr": 2.0,
        "sl_buffer_atr": 0.1,
        "min_sl_atr": 0.0,         # don't reject for tiny SL on synthetic
        "required_pattern": ["hammer", "bullish_engulfing"],
    }

    print("Uptrend + pullback + hammer should fire BUY:")
    df = _make_synthetic_uptrend_with_pullback()
    setup = find_entry(df, cfg, bar_idx=-1)
    check("setup found", setup is not None, "no setup")
    if setup:
        check("direction is BUY", setup.direction == "BUY", str(setup.direction))
        check("pattern is hammer", setup.pattern == "hammer", str(setup.pattern))
        check("SL below entry", setup.sl < setup.entry_price, f"sl={setup.sl} entry={setup.entry_price}")
        check("TP above entry", setup.tp > setup.entry_price, f"tp={setup.tp} entry={setup.entry_price}")

    print("Choppy market should NOT fire:")
    df = _make_synthetic_choppy()
    cfg_chop = {**cfg, "chop_band_atr": 0.5}   # require some distance from EMA
    setup = find_entry(df, cfg_chop, bar_idx=-1)
    check("no setup in chop", setup is None, str(setup))

    print("trend_flipped detector:")
    # Build a downtrend, ask if a SELL would still be valid (no flip) and a BUY would flip
    df_down = _make_synthetic_uptrend_with_pullback()   # ends in uptrend
    flipped_buy  = trend_flipped(df_down, "BUY",  ema_trend_period=50, bar_idx=-1)
    flipped_sell = trend_flipped(df_down, "SELL", ema_trend_period=50, bar_idx=-1, chop_band_atr=0.0)
    check("BUY in uptrend not flipped", flipped_buy is False, f"flipped_buy={flipped_buy}")
    check("SELL in uptrend IS flipped", flipped_sell is True, f"flipped_sell={flipped_sell}")

    print()
    if failures:
        print(f"FAIL: {len(failures)} test(s) failed")
        return 1
    print("All self-tests passed.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_self_tests())