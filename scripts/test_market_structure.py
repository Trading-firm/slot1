"""
scripts/test_market_structure.py
─────────────────────────────────
Phase 1 validation: fetch real gold data, run the structure classifier,
eyeball the output.

Shows:
  - Latest classification (UPTREND / DOWNTREND / RANGE / CHOPPY) per timeframe
  - The confirmed swing points it found (most recent 6)
  - A rolling classification over the last 50 bars so you can see how it
    shifts as the market moves
"""
import os, sys
import MetaTrader5 as mt5
import pandas as pd

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.market_structure import (
    find_swing_points, classify_trend,
    TREND_UP, TREND_DOWN, REGIME_RANGE, REGIME_CHOP,
)

SYMBOL = "XAUUSD"
TIMEFRAMES = [
    (mt5.TIMEFRAME_H4,  "H4",  400),
    (mt5.TIMEFRAME_H1,  "H1",  500),
    (mt5.TIMEFRAME_M15, "M15", 500),
]


def run_for_tf(tf, tf_name, count):
    df = fetch_candles(SYMBOL, tf, count=count)
    if df.empty:
        print(f"  {tf_name}: no data"); return
    report = classify_trend(df, left=5, right=5, min_swings=3, range_band_pct=2.0)

    print(f"\n── {tf_name} ({len(df)} bars, last close {df['Close'].iloc[-1]:.2f}) ──")
    print(f"  TREND:  {report.trend}")
    print(f"  Reason: {report.reason}")

    if report.swings:
        recent = report.swings[-6:]
        print(f"  Recent swings (last 6):")
        for s in recent:
            ago = len(df) - 1 - s.idx
            ts = df["time"].iloc[s.idx] if "time" in df.columns else s.idx
            print(f"    {s.kind:<4} @ ${s.price:>9.2f}  (bar idx {s.idx}, {ago} bars ago, time {ts})")
    else:
        print("  No swings detected yet.")

    if report.trend == REGIME_RANGE:
        print(f"  Range: support ${report.range_support:.2f} / resistance ${report.range_resistance:.2f}")
    elif report.trend == TREND_UP and report.last_highs and report.last_lows:
        print(f"  Last HH: ${report.last_highs[-1].price:.2f}  |  Last HL: ${report.last_lows[-1].price:.2f}")
    elif report.trend == TREND_DOWN and report.last_highs and report.last_lows:
        print(f"  Last LH: ${report.last_highs[-1].price:.2f}  |  Last LL: ${report.last_lows[-1].price:.2f}")


def rolling_classification(tf, tf_name, count, step=10):
    """Replay the classifier every `step` bars over the last 100 bars."""
    df = fetch_candles(SYMBOL, tf, count=count)
    if df.empty or len(df) < 100: return

    print(f"\n── ROLLING {tf_name} (last 100 bars, every {step} bars) ──")
    print(f"  {'Ending bar':<12} {'Time':<22} {'Close':<10} {'Trend':<10} {'Reason'}")
    for i in range(len(df) - 100, len(df), step):
        sub = df.iloc[:i+1]
        r = classify_trend(sub, left=5, right=5, min_swings=3, range_band_pct=2.0)
        ts = sub["time"].iloc[-1] if "time" in sub.columns else i
        print(f"  {i:<12} {str(ts):<22} ${sub['Close'].iloc[-1]:<8.2f} {r.trend:<10} {r.reason}")


def main():
    if not connect(): print("MT5 connect failed"); return
    mt5.symbol_select(SYMBOL, True)

    print("="*90)
    print(f"PHASE 1 VALIDATION: market structure detection on {SYMBOL}")
    print("="*90)

    for tf, tf_name, count in TIMEFRAMES:
        run_for_tf(tf, tf_name, count)

    print("\n" + "="*90)
    print("SANITY — does the classifier shift as price evolves?")
    print("="*90)
    for tf, tf_name, count in TIMEFRAMES:
        rolling_classification(tf, tf_name, count, step=10)

    disconnect()


if __name__ == "__main__":
    main()