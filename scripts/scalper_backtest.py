"""
scripts/scalper_backtest.py
────────────────────────────
Backtest the momentum candle scalper across Forex pairs WITH spread cost
modeled honestly.

Spread modeling:
  - Entry filled at next bar's OPEN (broker buys at ask, sells at bid)
  - We subtract `spread_price` from each trade's PnL once
  - Equivalent to: entry slip = +spread (buy) / -spread (sell), measured in price

Sweep dimensions:
  - timeframe: M5, M15
  - body_min_pct: 0.5, 0.6, 0.7
  - rr_ratio: 1.0, 1.5, 2.0
  - use_ema_filter: True / False
  - min_range_x_spread: 3, 4

Score = expectancy_in_R * sqrt(trades).
"""
import os, sys, math, itertools
from collections import defaultdict
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())

from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.scalper import generate_scalp_signal
from strategies.indicators import calc_ema, calc_atr

DAYS = 90
MIN_TRADES = 30   # require sample size

# Conservative trading-hour spread estimates per pair (PRICE units, not pips)
# We use these in backtest because weekend spreads are misleadingly low.
SPREAD_PRICE = {
    "EURUSD": 0.00003,   # 0.3 pip
    "GBPUSD": 0.00004,   # 0.4 pip
    "AUDUSD": 0.00003,   # 0.3 pip
    "USDJPY": 0.004,     # 0.4 pip (JPY pip = 0.01)
    "USDCHF": 0.00005,   # 0.5 pip
    "NZDUSD": 0.00005,   # 0.5 pip
    "EURGBP": 0.00007,   # 0.7 pip
}

PAIRS = list(SPREAD_PRICE.keys())

TIMEFRAMES = [
    (mt5.TIMEFRAME_M5,  "M5",  288),
    (mt5.TIMEFRAME_M15, "M15", 96),
]

# Sweep grid
BODY_MIN_PCTS  = [0.5, 0.6, 0.7]
RR_RATIOS      = [1.0, 1.5, 2.0]
EMA_FILTERS    = [True, False]
MIN_RANGE_X    = [3, 4]


def run_one(df, spread_price, body_min_pct, rr_ratio, use_ema, min_range_x):
    """One backtest run. Returns trade stats dict."""
    cfg = {"filters": {
        "body_min_pct":       body_min_pct,
        "body_lookback":      5,
        "close_extremity":    1/3,
        "min_range_x_spread": min_range_x,
        "use_ema_filter":     use_ema,
        "ema_period":         8,
        "sl_buffer_atr":      0.1,
        "rr_ratio":           rr_ratio,
        "atr_period":         14,
    }}

    n = len(df)
    if n < 50:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0, "exp_R": 0, "net_R": 0, "net_pips": 0}

    # Pre-extract arrays for speed
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values

    trades_R     = []   # signed R units after spread cost
    trades_pips  = []   # signed price units after spread cost
    pip_size     = 0.01 if 'JPY' in df.attrs.get("symbol", "") else 0.0001

    active = None
    cooldown_until = -1

    for i in range(50, n - 1):
        if active is None and i > cooldown_until:
            # Slice DF up to i+1 (inclusive of bar i, the just-closed candle)
            sl_df = df.iloc[:i+1]
            sig = generate_scalp_signal(sl_df, cfg, spread_price=spread_price)
            if sig.direction != "NONE":
                # Enter at next bar's open
                entry = o[i+1]
                if sig.direction == "BUY":
                    # SL/TP relative to actual entry, keep distances
                    sl_dist = sig.entry - sig.sl
                    tp_dist = sig.tp   - sig.entry
                    sl_price = entry - sl_dist
                    tp_price = entry + tp_dist
                else:
                    sl_dist = sig.sl   - sig.entry
                    tp_dist = sig.entry - sig.tp
                    sl_price = entry + sl_dist
                    tp_price = entry - tp_dist
                active = {
                    "dir":     sig.direction,
                    "entry":   entry,
                    "sl":      sl_price,
                    "tp":      tp_price,
                    "sl_dist": sl_dist,
                    "tp_dist": tp_dist,
                    "bar":     i+1,
                }
                # Skip evaluation on entry bar itself; check from bar i+2

        if active is not None and i+1 > active["bar"]:
            # Check current bar i+1 for SL/TP hit
            bh, bl = h[i+1], l[i+1]
            hit_sl = hit_tp = False
            if active["dir"] == "BUY":
                if bl <= active["sl"]: hit_sl = True
                elif bh >= active["tp"]: hit_tp = True
            else:
                if bh >= active["sl"]: hit_sl = True
                elif bl <= active["tp"]: hit_tp = True

            if hit_sl or hit_tp:
                # Spread cost paid once per trade (subtracted from P/L)
                if hit_tp:
                    pnl_price = active["tp_dist"] - spread_price
                else:
                    pnl_price = -(active["sl_dist"] + spread_price)
                trades_pips.append(pnl_price / pip_size)
                trades_R.append(pnl_price / active["sl_dist"])
                cooldown_until = i + 2   # 1-bar cooldown after exit
                active = None

    if not trades_R:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0, "exp_R": 0, "net_R": 0, "net_pips": 0}

    wins   = sum(1 for r in trades_R if r > 0)
    losses = len(trades_R) - wins
    wr     = wins / len(trades_R)
    net_R  = sum(trades_R)
    exp_R  = net_R / len(trades_R)
    net_pips = sum(trades_pips)
    return {
        "trades":   len(trades_R),
        "wins":     wins,
        "losses":   losses,
        "wr":       round(wr * 100, 2),
        "net_R":    round(net_R, 2),
        "exp_R":    round(exp_R, 3),
        "net_pips": round(net_pips, 1),
    }


def sweep_pair(symbol, timeframe, tf_name, bars_per_day, spread_price):
    df = fetch_candles(symbol, timeframe, count=bars_per_day * DAYS + 200)
    if df.empty or len(df) < 500:
        return []
    df.attrs["symbol"] = symbol
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

    rows = []
    for body, rr, ema, mr in itertools.product(BODY_MIN_PCTS, RR_RATIOS, EMA_FILTERS, MIN_RANGE_X):
        r = run_one(df, spread_price, body, rr, ema, mr)
        r["tpd"]      = round(r["trades"] / days, 2)
        r["body"]     = body
        r["rr"]       = rr
        r["ema"]      = ema
        r["mr"]       = mr
        r["tf"]       = tf_name
        r["score"]    = round(r["exp_R"] * math.sqrt(max(r["trades"], 1)), 3)
        rows.append(r)
    return rows


def main():
    if not connect():
        print("MT5 connect failed"); return

    # Enable symbols
    for s in PAIRS:
        mt5.symbol_select(s, True)

    print("="*100)
    print(f"SCALPER SWEEP — {len(PAIRS)} pairs x {len(TIMEFRAMES)} TFs x "
          f"{len(BODY_MIN_PCTS)*len(RR_RATIOS)*len(EMA_FILTERS)*len(MIN_RANGE_X)} configs ({DAYS} days)")
    print("="*100)

    best_per_pair = {}
    for sym in PAIRS:
        spread = SPREAD_PRICE[sym]
        print(f"\n--- {sym} (spread={spread}) ---")
        all_rows = []
        for tf, tf_name, bpd in TIMEFRAMES:
            rows = sweep_pair(sym, tf, tf_name, bpd, spread)
            all_rows.extend(rows)
        eligible = [r for r in all_rows if r["trades"] >= MIN_TRADES]
        if not eligible:
            print("  No config produced enough trades")
            continue
        eligible.sort(key=lambda r: r["score"], reverse=True)
        best = eligible[0]
        print(f"  TOP: {best['tf']} body={best['body']} rr=1:{best['rr']} ema={best['ema']} mr={best['mr']} "
              f"-> {best['trades']} tr | {best['tpd']} T/D | WR {best['wr']}% | exp {best['exp_R']:+.3f}R | "
              f"net {best['net_R']:+.2f}R / {best['net_pips']:+.1f}pips | score {best['score']:+.2f}")
        # Show top 3 for context
        for r in eligible[1:3]:
            print(f"       {r['tf']} body={r['body']} rr=1:{r['rr']} ema={r['ema']} mr={r['mr']} "
                  f"-> {r['trades']} tr | {r['tpd']} T/D | WR {r['wr']}% | exp {r['exp_R']:+.3f}R | "
                  f"score {r['score']:+.2f}")
        best_per_pair[sym] = best

    disconnect()

    # Final summary
    print("\n" + "="*100)
    print("BEST CONFIG PER PAIR (ranked by expectancy * sqrt(trades))")
    print("="*100)
    print(f"{'Pair':<8} {'TF':<4} {'Body':<5} {'R:R':<5} {'EMA':<6} {'MR':<3} | {'Trades':<7} {'T/D':<5} {'WR%':<6} {'Exp':<7} {'NetR':<7} {'Pips':<7}")
    print("-"*100)
    total_trades = 0
    total_net_R = 0.0
    total_tpd = 0.0
    for sym, b in best_per_pair.items():
        print(f"{sym:<8} {b['tf']:<4} {b['body']:<5} {b['rr']:<5} {str(b['ema']):<6} {b['mr']:<3} | "
              f"{b['trades']:<7} {b['tpd']:<5} {b['wr']:<6} {b['exp_R']:+7.3f} {b['net_R']:+7.2f} {b['net_pips']:+7.1f}")
        total_trades += b['trades']
        total_net_R += b['net_R']
        total_tpd += b['tpd']
    print("-"*100)
    print(f"{'TOTAL':<8} -- combined: {total_trades} trades over {DAYS}d | {total_tpd:.2f} T/D combined | "
          f"net {total_net_R:+.2f}R")


if __name__ == "__main__":
    main()