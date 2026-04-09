import os
import sys
import pandas as pd

# Add project root to path
sys.path.append(os.getcwd())

from config.markets import MARKETS
from strategies.signal_engine import generate_signal
from broker.mt5_connector import connect, disconnect, fetch_candles

def run_backtest(symbol, cfg, days=30):
    print(f"\n--- Backtesting {symbol} on {cfg['tf_name']} for last {days} days ---")

    if not connect():
        print("Failed to connect to MT5")
        return None

    candles_per_day = {
        "M5": 288,
        "M15": 96,
        "M30": 48,
        "H1": 24
    }
    count = candles_per_day.get(cfg['tf_name'], 24) * days

    df = fetch_candles(symbol, cfg["timeframe"], count=count)
    if df.empty:
        print(f"No data for {symbol}")
        return None

    trades = []
    active_trade = None

    for i in range(250, len(df) - 1):
        current_df = df.iloc[:i+1]

        if not active_trade:
            signal = generate_signal(current_df, cfg)
            if signal.direction != "NONE":
                active_trade = {
                    "entry_price": signal.close,
                    "direction":   signal.direction,
                    "sl":          signal.sl,
                    "tp":          signal.tp1,   # Use TP1 for backtest
                    "entry_time":  df.index[i]
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
                pnl = 1.0 if hit_tp else -1.0
                trades.append(pnl)
                active_trade = None

    if not trades:
        return {"win_rate": 0, "total_trades": 0, "profit_pct": 0, "rr_ratio": 0, "wins": 0}

    wins     = [t for t in trades if t > 0]
    win_rate = (len(wins) / len(trades)) * 100

    sl_mult = cfg.get("atr_sl", 2.0)
    tp_mult = cfg.get("atr_tp", 3.0)
    rr = tp_mult / sl_mult

    total_profit_pct = sum([rr if t > 0 else -1.0 for t in trades])

    return {
        "win_rate":     round(win_rate, 2),
        "total_trades": len(trades),
        "wins":         len(wins),
        "profit_pct":   round(total_profit_pct, 2),
        "rr_ratio":     round(rr, 2)
    }

def main():
    symbols_to_test    = ["BTCUSD"]
    strategies_to_test = ["trend_following", "smc", "breakout"]

    summary = []

    for symbol in symbols_to_test:
        if symbol not in MARKETS:
            print(f"Symbol {symbol} not found in MARKETS config — skipping")
            continue

        for strategy in strategies_to_test:
            cfg = MARKETS[symbol].copy()
            cfg["strategy"] = strategy
            results = run_backtest(symbol, cfg, days=60)

            if results:
                summary.append({
                    "symbol":   symbol,
                    "strategy": strategy.upper(),
                    "win_rate": results["win_rate"],
                    "profit":   results["profit_pct"],
                    "trades":   results["total_trades"]
                })

    if summary:
        print("\n" + "="*80)
        print(f"{'MARKET':<10} | {'STRATEGY':<20} | {'WIN RATE':<10} | {'PROFIT':<10} | {'TRADES':<10}")
        print("-" * 80)
        for s in summary:
            print(f"{s['symbol']:<10} | {s['strategy']:<20} | {s['win_rate']:>8}% | {s['profit']:>8}% | {s['trades']:>10}")
        print("="*80 + "\n")
    else:
        print("No results generated. Check market configurations or session windows.")

if __name__ == "__main__":
    main()
