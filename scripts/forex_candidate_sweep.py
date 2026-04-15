"""
scripts/forex_candidate_sweep.py
─────────────────────────────────
Scans a list of Forex candidates, runs the full parameter sweep on each
at both M15 and M30, and reports the best configs ranked by edge.

Used to select NEW markets to add to config/markets.py.
"""
import os, sys, math, itertools
import MetaTrader5 as mt5

sys.path.append(os.getcwd())

from broker.mt5_connector import connect, disconnect, fetch_candles, get_symbol_info
from strategies.indicators import calc_swing_points
from scripts.backtest_sweep import (
    precompute, precompute_htf_trend, run_backtest, build_combos,
    ADX_VALUES, RSI_BANDS, HTF_VALUES, PULLBACK_TOL, SESSION_MODES,
    BARS_PER_DAY,
)

DAYS = 90
MIN_TRADES = 25   # require decent sample size

# Curated liquid Forex candidates (not already in markets.py)
CANDIDATES = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD",
    "GBPAUD", "GBPCHF", "GBPNZD",
    "AUDCAD", "AUDCHF", "AUDNZD", "NZDCAD", "NZDCHF",
    "NZDJPY", "CADJPY", "CHFJPY", "SGDJPY",
]

TIMEFRAMES = [
    (mt5.TIMEFRAME_M15, "M15"),
    (mt5.TIMEFRAME_M30, "M30"),
]


def sweep_symbol(symbol, timeframe, tf_name):
    count = BARS_PER_DAY[tf_name] * DAYS + 300
    df = fetch_candles(symbol, timeframe, count=count)
    if df.empty or len(df) < 500:
        return None
    htf_df = fetch_candles(symbol, mt5.TIMEFRAME_H1, count=DAYS * 24 + 300)

    ind = precompute(df)
    htf = precompute_htf_trend(htf_df) if not htf_df.empty else None
    sw_h, sw_l = calc_swing_points(df, window=10)
    sw_h, sw_l = sw_h.values, sw_l.values

    days_in = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

    # Default sessions to London for Forex baseline (sweep will test others)
    combos = build_combos([{"start": 8, "end": 17}])
    results = []
    for cp in combos:
        r = run_backtest(ind, htf, cp, sw_h, sw_l)
        r["trades_per_day"] = round(r["trades"] / days_in, 2)
        r["adx_min"]      = cp["adx_min"]
        r["rsi_key"]      = cp["rsi_key"]
        r["htf_on"]       = cp["htf_on"]
        r["pullback_key"] = cp["pullback_key"]
        r["session_key"]  = cp["session_key"]
        results.append(r)

    eligible = [r for r in results if r["trades"] >= MIN_TRADES]
    if not eligible:
        return None
    eligible.sort(key=lambda r: r["expectancy"] * math.sqrt(r["trades"]), reverse=True)
    best = eligible[0]
    best["symbol"]   = symbol
    best["tf_name"]  = tf_name
    best["score"]    = round(best["expectancy"] * math.sqrt(best["trades"]), 3)
    return best


def main():
    print("="*100)
    print(f"FOREX CANDIDATE SWEEP — {len(CANDIDATES)} pairs x 2 TFs x 72 configs — {DAYS} days")
    print("="*100)

    if not connect():
        print("MT5 connect failed"); return

    all_best = []
    for sym in CANDIDATES:
        info = get_symbol_info(sym)
        if info is None:
            print(f"  {sym}: not available, skipping")
            continue
        for tf, tf_name in TIMEFRAMES:
            best = sweep_symbol(sym, tf, tf_name)
            if best is None:
                print(f"  {sym} {tf_name}: insufficient data")
                continue
            print(f"  {sym} {tf_name}: WR {best['win_rate']:>5.1f}% | {best['trades']:>3} tr | "
                  f"{best['trades_per_day']:>4} T/D | exp {best['expectancy']:+.2f} | "
                  f"score {best['score']:+.2f} | ADX>={best['adx_min']} {best['rsi_key']} "
                  f"HTF={best['htf_on']} {best['pullback_key']} {best['session_key']}")
            all_best.append(best)

    disconnect()

    # Rank by score
    all_best.sort(key=lambda r: r["score"], reverse=True)

    print("\n" + "="*100)
    print("TOP 15 CANDIDATES (ranked by expectancy * sqrt(trades))")
    print("="*100)
    print(f"{'Sym':<8} {'TF':<4} {'WR%':<6} {'Tr':<4} {'T/D':<5} {'Exp':<6} {'Score':<6} | {'ADX':<4} {'RSI':<7} {'HTF':<5} {'Pull':<7} {'Session':<9}")
    print("-"*100)
    for r in all_best[:15]:
        print(f"{r['symbol']:<8} {r['tf_name']:<4} {r['win_rate']:<6} {r['trades']:<4} {r['trades_per_day']:<5} {r['expectancy']:+6.2f} {r['score']:+6.2f} |"
              f" {r['adx_min']:<4} {r['rsi_key']:<7} {str(r['htf_on']):<5} {r['pullback_key']:<7} {r['session_key']:<9}")

    # Dedupe by symbol (keep best TF)
    seen = set()
    top5 = []
    for r in all_best:
        if r["symbol"] in seen: continue
        seen.add(r["symbol"])
        top5.append(r)
        if len(top5) == 5: break

    print("\n" + "="*100)
    print("RECOMMENDED TOP 5 NEW MARKETS (one TF per symbol)")
    print("="*100)
    for r in top5:
        print(f"  {r['symbol']} {r['tf_name']}: WR {r['win_rate']:>5.1f}% | {r['trades_per_day']:>4} T/D | "
              f"exp {r['expectancy']:+.2f} | ADX>={r['adx_min']} {r['rsi_key']} HTF={r['htf_on']} "
              f"{r['pullback_key']} {r['session_key']}")


if __name__ == "__main__":
    main()
