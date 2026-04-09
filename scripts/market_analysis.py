"""
scripts/market_analysis.py
───────────────────────────
Fast O(n) market analysis backtester.
Indicators are pre-computed once per combo; the bar loop just reads values.

Usage:
    python scripts/market_analysis.py GBPUSD
    python scripts/market_analysis.py GBPUSD --days 90
"""

import os
import sys
import math
import argparse
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from broker.mt5_connector import connect, disconnect, fetch_candles

# Silence loguru AFTER all bot imports so re-added sinks are removed
from loguru import logger as _loguru_logger
_loguru_logger.remove()

from strategies.indicators import (
    calc_ema, calc_rsi, calc_atr, calc_adx,
    calc_bollinger_bands, calc_swing_points,
)


# ─── Fast Indicator Pre-Computation ──────────────────────────────────────────

def precompute(df: pd.DataFrame, cfg: dict) -> dict:
    """Compute all indicators on the full dataframe once. O(n)."""
    f = cfg["filters"]
    return {
        "atr":   calc_atr(df, cfg.get("atr_period", 14)).values,
        "rsi":   calc_rsi(df, f.get("rsi_period", 14)).values,
        "ema_f": calc_ema(df, f.get("ema_fast", 20)).values,
        "ema_s": calc_ema(df, f.get("ema_slow", 50)).values,
        "ema_t": calc_ema(df, f.get("ema_trend", 200)).values,
        "adx":   calc_adx(df, f.get("adx_period", 14)).values,
        "bb_u":  calc_bollinger_bands(df, 20)[0].values,
        "bb_l":  calc_bollinger_bands(df, 20)[1].values,
        "sw_h":  calc_swing_points(df, cfg.get("swing_window", 10))[0].values,
        "sw_l":  calc_swing_points(df, cfg.get("swing_window", 10))[1].values,
    }


def get_signal_fast(df, ind, cfg, i):
    """
    Generate signal at bar index i using pre-computed indicators.
    Uses bar i-1 (last completed candle) to avoid lookahead.
    Returns (direction, sl, tp1, tp2, tp3) or ("NONE", 0, 0, 0, 0).
    """
    idx = i - 1      # last completed candle
    if idx < 5:
        return "NONE", 0, 0, 0, 0

    f        = cfg["filters"]
    strategy = cfg["strategy"]

    atr   = ind["atr"][idx]
    rsi   = ind["rsi"][idx]
    ema_f = ind["ema_f"][idx]
    ema_s = ind["ema_s"][idx]
    ema_t = ind["ema_t"][idx]
    adx   = ind["adx"][idx]

    if any(math.isnan(v) for v in [atr, rsi, ema_f, ema_s, ema_t, adx]):
        return "NONE", 0, 0, 0, 0

    # Session filter
    sessions = f.get("sessions", [])
    if sessions and "time" in df.columns:
        import pandas as _pd
        t = df["time"].iloc[idx]
        if not isinstance(t, _pd.Timestamp):
            t = _pd.to_datetime(t)
        hour_wat = (t.hour + 1) % 24   # WAT = UTC+1
        if not any(s["start"] <= hour_wat <= s["end"] for s in sessions):
            return "NONE", 0, 0, 0, 0

    close  = df["Close"].iloc[idx]
    o      = df["Open"].iloc[idx]
    hi     = df["High"].iloc[idx]
    lo     = df["Low"].iloc[idx]

    adx_min = f.get("adx_min", 25)
    uptrend   = ema_s > ema_t and close > ema_t
    downtrend = ema_s < ema_t and close < ema_t

    rsi_ok_buy  = f.get("rsi_min_buy",  35) <= rsi <= f.get("rsi_max_buy",  58)
    rsi_ok_sell = f.get("rsi_min_sell", 42) <= rsi <= f.get("rsi_max_sell", 65)

    base_dir = "NONE"

    if strategy == "trend_following" and adx > adx_min:
        bull_close = close > o
        bear_close = close < o
        if uptrend   and lo <= ema_f and close > ema_f and bull_close and rsi_ok_buy:
            base_dir = "BUY"
        elif downtrend and hi >= ema_f and close < ema_f and bear_close and rsi_ok_sell:
            base_dir = "SELL"

    elif strategy == "trend_following_breakout" and adx > adx_min:
        # Combines pullback + momentum breakout
        bull_close = close > o
        bear_close = close < o
        bb_u = ind["bb_u"][idx]
        bb_l = ind["bb_l"][idx]
        bb_u_prev = ind["bb_u"][idx-1] if idx > 0 else bb_u
        bb_l_prev = ind["bb_l"][idx-1] if idx > 0 else bb_l
        c_prev = df["Close"].iloc[idx-1]

        if not base_dir and uptrend and lo <= ema_f and close > ema_f and bull_close and rsi_ok_buy:
            base_dir = "BUY"
        if not base_dir and downtrend and hi >= ema_f and close < ema_f and bear_close and rsi_ok_sell:
            base_dir = "SELL"
        if not base_dir and uptrend and adx > adx_min and close > bb_u and c_prev <= bb_u_prev:
            base_dir = "BUY"
        if not base_dir and downtrend and adx > adx_min and close < bb_l and c_prev >= bb_l_prev:
            base_dir = "SELL"

    elif strategy == "breakout" and adx > adx_min:
        bb_u = ind["bb_u"][idx]
        bb_l = ind["bb_l"][idx]
        if idx > 0:
            bb_u_prev = ind["bb_u"][idx-1]
            bb_l_prev = ind["bb_l"][idx-1]
            c_prev    = df["Close"].iloc[idx-1]
            if close > ema_t and close > bb_u and c_prev <= bb_u_prev:
                base_dir = "BUY"
            elif close < ema_t and close < bb_l and c_prev >= bb_l_prev:
                base_dir = "SELL"

    if base_dir == "NONE":
        return "NONE", 0, 0, 0, 0

    # SL / TP
    sw    = cfg.get("swing_window", 10)
    start = max(0, idx - sw)
    r_low  = np.nanmin(ind["sw_l"][start:idx])
    r_high = np.nanmax(ind["sw_h"][start:idx])
    max_sl = atr * cfg.get("max_sl_atr", 2.5)

    if base_dir == "BUY":
        sl = r_low - atr * 0.2
        sl_d = close - sl
        if sl_d <= 0 or sl_d > max_sl:
            return "NONE", 0, 0, 0, 0
        tp1 = close + sl_d * 1.0
        tp2 = close + sl_d * 2.0
        tp3 = r_high if r_high > tp2 + atr * 0.5 else close + sl_d * 3.0
    else:
        sl = r_high + atr * 0.2
        sl_d = sl - close
        if sl_d <= 0 or sl_d > max_sl:
            return "NONE", 0, 0, 0, 0
        tp1 = close - sl_d * 1.0
        tp2 = close - sl_d * 2.0
        tp3 = r_low if r_low < tp2 - atr * 0.5 else close - sl_d * 3.0

    return base_dir, sl, tp1, tp2, tp3


# ─── Fast Backtest Runner ────────────────────────────────────────────────────

def run_combo(df, cfg, label):
    ind = precompute(df, cfg)
    trades       = []
    active_trade = None

    for i in range(252, len(df) - 1):
        if not active_trade:
            direction, sl, tp1, tp2, tp3 = get_signal_fast(df, ind, cfg, i)
            if direction != "NONE":
                active_trade = {
                    "direction": direction,
                    "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
                }
        else:
            nxt_lo = df["Low"].iloc[i+1]
            nxt_hi = df["High"].iloc[i+1]
            t = active_trade

            hit_sl  = (nxt_lo <= t["sl"])  if t["direction"] == "BUY" else (nxt_hi >= t["sl"])
            hit_tp1 = (nxt_hi >= t["tp1"]) if t["direction"] == "BUY" else (nxt_lo <= t["tp1"])

            if hit_sl:
                trades.append(-1.0)
                active_trade = None
            elif hit_tp1:
                trades.append(1.0)
                active_trade = None

    if not trades:
        return None

    wins   = sum(1 for t in trades if t > 0)
    losses = len(trades) - wins
    wr     = wins / len(trades) * 100

    return {
        "label":  label,
        "wr":     round(wr, 1),
        "trades": len(trades),
        "wins":   wins,
        "losses": losses,
        "net_r":  round(wins - losses, 1),
        "tpd":    round(len(trades) / (len(df) / ({"M15":96,"M30":48,"H1":24}.get(cfg["tf_name"],96))), 2),
    }


# ─── Config Builder ──────────────────────────────────────────────────────────

def build_configs(symbol):
    TFS = [
        (mt5.TIMEFRAME_M15, "M15"),
        (mt5.TIMEFRAME_M30, "M30"),
        (mt5.TIMEFRAME_H1,  "H1"),
    ]
    STRATEGIES = ["trend_following", "trend_following_breakout", "breakout"]
    ADX_LEVELS = [20, 25, 30]
    SESSION_SETS = [
        ("24/7",      []),                          # No filter — all hours
        ("London+US", [{"start": 8,  "end": 22}]),
        ("London",    [{"start": 8,  "end": 17}]),
        ("US",        [{"start": 14, "end": 22}]),
    ]

    configs = []
    for tf, tf_name in TFS:
        for strat in STRATEGIES:
            for adx in ADX_LEVELS:
                for sess_label, sessions in SESSION_SETS:
                    label = f"{tf_name} | {strat:<24} | ADX>={adx} | {sess_label}"
                    configs.append((label, {
                        "symbol":       symbol,
                        "timeframe":    tf,
                        "tf_name":      tf_name,
                        "strategy":     strat,
                        "filters": {
                            "ema_fast": 20, "ema_slow": 50, "ema_trend": 200,
                            "adx_period": 14, "adx_min": adx,
                            "rsi_period": 14,
                            "rsi_min_buy": 35, "rsi_max_buy": 58,
                            "rsi_min_sell": 42, "rsi_max_sell": 65,
                            "sessions": sessions,
                        },
                        "max_sl_atr":   2.5,
                        "swing_window": 10,
                        "min_lot":      0.01,
                        "atr_period":   14,
                    }))
    return configs


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol",       nargs="?", default="GBPUSD")
    parser.add_argument("--days",       type=int,  default=60)
    parser.add_argument("--min-trades", type=int,  default=10)
    args = parser.parse_args()

    symbol = args.symbol
    days   = args.days

    print(f"\n{'='*75}")
    print(f"  MARKET ANALYSIS: {symbol}  |  {days}-day backtest  |  O(n) fast mode")
    print(f"{'='*75}\n")

    if not connect():
        print("Failed to connect to MT5")
        return

    configs = build_configs(symbol)
    print(f"Running {len(configs)} combinations...\n")

    # Pre-fetch all timeframes once
    cpd = {"M15": 96, "M30": 48, "H1": 24}
    dfs = {}
    for tf, tf_name in [(mt5.TIMEFRAME_M15,"M15"),(mt5.TIMEFRAME_M30,"M30"),(mt5.TIMEFRAME_H1,"H1")]:
        count = cpd[tf_name] * days + 300
        df = fetch_candles(symbol, tf, count=count)
        dfs[tf_name] = df
        status = f"{len(df)} bars" if not df.empty else "NO DATA"
        print(f"  {tf_name}: {status}")

    disconnect()
    print()

    results = []
    for i, (label, cfg) in enumerate(configs, 1):
        df = dfs.get(cfg["tf_name"], pd.DataFrame())
        if df.empty:
            continue
        res = run_combo(df, cfg, label)
        if res and res["trades"] >= args.min_trades:
            results.append(res)
        if i % 27 == 0:
            print(f"  [{i}/{len(configs)}] done...")

    if not results:
        print("No combinations produced enough trades.")
        return

    results.sort(key=lambda r: (r["wr"], r["net_r"]), reverse=True)

    HDR = f"{'Configuration':<57} | {'WinRate':>8} | {'Trades':>7} | {'W':>4} | {'L':>4} | {'NetR':>6} | {'T/Day':>6}"
    SEP = "=" * len(HDR)
    print(SEP)
    print(HDR)
    print("-" * len(HDR))
    for r in results:
        mk = " *" if r["net_r"] > 0 else "  "
        print(f"{r['label']:<57} | {r['wr']:>7}% | {r['trades']:>7} | "
              f"{r['wins']:>4} | {r['losses']:>4} | {r['net_r']:>+6.1f} | {r['tpd']:>6.2f}{mk}")
    print(SEP)
    print("  * = Net-positive at 1:1 R:R.  With 3-TP system avg winner ~2R (better)")

    print(f"\n  TOP 5 BY WIN RATE:")
    for r in results[:5]:
        est_3tp = r["wins"] * 2.0 - r["losses"] * 1.0
        print(f"    {r['wr']:>5}% | {r['trades']:>3} trades | "
              f"1:1 NetR={r['net_r']:+.0f}R | 3-TP est={est_3tp:+.0f}R | {r['label']}")

    best = results[0]
    print(f"\n  VERDICT: {'ADD' if best['net_r'] > 0 and best['wr'] >= 45 else 'SKIP'}")
    print(f"    Best config : {best['label']}")
    print(f"    Win rate    : {best['wr']}%")
    print(f"    Trades      : {best['trades']} in {days} days ({best['tpd']}/day)")
    print(f"    Net R (1:1) : {best['net_r']:+.1f}R")
    est = best['wins'] * 2.0 - best['losses'] * 1.0
    print(f"    Est R (3-TP): {est:+.1f}R")
    print()


if __name__ == "__main__":
    main()
