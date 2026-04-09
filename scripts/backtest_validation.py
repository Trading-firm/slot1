import os
import sys
import pandas as pd

sys.path.append(os.getcwd())

from config.markets import MARKETS
from strategies.signal_engine import generate_signal
from broker.mt5_connector import connect, disconnect, fetch_candles

def backtest_market(symbol, cfg, days=30):
    print(f"\n--- Backtesting {symbol} ({days} days) ---")

    if not connect():
        print("Failed to connect to MT5")
        return None

    candles_per_day = {"M5": 288, "M15": 96, "M30": 48, "H1": 24}
    count = candles_per_day.get(cfg["tf_name"], 96) * days

    df = fetch_candles(symbol, cfg["timeframe"], count=count)
    if df.empty:
        print(f"No data for {symbol}")
        return None

    # Pre-fetch full H1 history for HTF filter (bar-by-bar slicing below)
    htf_tf   = cfg.get("filters", {}).get("htf_timeframe")
    htf_full = None
    if htf_tf:
        # H1 count: we need enough bars to cover the same date range + 200 for EMA
        htf_count = days * 24 + 250
        htf_full  = fetch_candles(symbol, htf_tf, count=htf_count)
        if htf_full.empty:
            htf_full = None

    trades       = []
    active_trade = None

    # Bar-by-bar simulation
    for i in range(250, len(df) - 1):
        current_df = df.iloc[:i+1]

        # Slice H1 data up to the current M15 candle timestamp
        htf_slice = None
        if htf_full is not None and "time" in df.columns:
            current_time = df["time"].iloc[i]
            mask         = htf_full["time"] <= current_time
            htf_slice    = htf_full[mask] if mask.any() else None

        if not active_trade:
            signal = generate_signal(current_df, cfg, htf_df=htf_slice)
            if signal.direction != "NONE":
                active_trade = {
                    "entry_price": signal.close,
                    "direction":   signal.direction,
                    "sl":          signal.sl,
                    "tp":          signal.tp1,
                    "entry_time":  df["time"].iloc[i] if "time" in df.columns else i,
                }
        else:
            low  = df["Low"].iloc[i+1]
            high = df["High"].iloc[i+1]

            hit_sl = False
            hit_tp = False

            if active_trade["direction"] == "BUY":
                if low  <= active_trade["sl"]: hit_sl = True
                elif high >= active_trade["tp"]: hit_tp = True
            else:
                if high >= active_trade["sl"]: hit_sl = True
                elif low  <= active_trade["tp"]: hit_tp = True

            if hit_sl or hit_tp:
                trades.append(1.0 if hit_tp else -1.0)
                active_trade = None

    disconnect()

    if not trades:
        return {"win_rate": 0, "total_trades": 0, "profit_pct": 0}

    wins     = [t for t in trades if t > 0]
    losses   = [t for t in trades if t < 0]
    win_rate = len(wins) / len(trades) * 100

    # At 1:1 R:R (TP1), each win = +1R, each loss = -1R
    net_r = len(wins) * 1.0 - len(losses) * 1.0

    return {
        "win_rate":     round(win_rate, 2),
        "total_trades": len(trades),
        "wins":         len(wins),
        "losses":       len(losses),
        "net_r":        round(net_r, 1),
        "profit_pct":   round(net_r, 2),
    }

def main():
    print("=" * 60)
    print("BACKTEST - Improved Strategy (ADX>=25, RSI filter, H1 HTF)")
    print("=" * 60)

    results = {}
    for symbol, cfg in MARKETS.items():
        res = backtest_market(symbol, cfg, days=60)
        if res:
            results[symbol] = res

    print("\n" + "=" * 60)
    print(f"{'Market':<10} | {'Win Rate':<10} | {'Trades':<8} | {'Wins':<6} | {'Losses':<8} | {'Net R':<8}")
    print("-" * 60)
    for market, d in results.items():
        print(
            f"{market:<10} | {d['win_rate']:>8}% | {d['total_trades']:>8} | "
            f"{d['wins']:>6} | {d['losses']:>8} | {d['net_r']:>+8.1f}R"
        )
    print("=" * 60)

if __name__ == "__main__":
    main()
