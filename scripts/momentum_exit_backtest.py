"""
scripts/momentum_exit_backtest.py
──────────────────────────────────
Honest backtest matching the LIVE bot behaviour:
  - Enter on strong momentum candle (body >= 0.75)
  - Exit when momentum fades (next bars' body < 0.5 AND we have profit/BE)
  - If small loss + weak market: wait for recovery
  - Structural SL as hard safety
  - No fixed TP (let momentum carry as far as it goes, exit when it stops)

This is what the user actually described: "ride the momentum, escape when it ends."
"""
import os, sys, itertools
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

DAYS = 90


def backtest(df, spread_price, lot, contract, body_min, use_ema, min_range_x,
             weak_threshold, be_tolerance_usd, small_loss_limit_usd,
             hard_sl_atr_mult=2.0):
    """
    Momentum-in momentum-out backtest.

    Entry rules = same as live (body >= body_min + other filters).
    Exit rules (in priority order):
      1. Hard SL hit (price goes past entry - hard_sl_atr_mult*ATR) -> lose
      2. Weak current bar (body < weak_threshold):
           profit >= be_tol              -> close in profit
           at BE (within +/- be_tol)     -> close at BE
           small loss (> -small_loss)    -> hold (wait for recovery)
           big loss (<= -small_loss)     -> hold (SL will catch)
      3. Strong current bar -> hold
    """
    o = df["Open"].values.astype(np.float64)
    h = df["High"].values.astype(np.float64)
    l = df["Low"].values.astype(np.float64)
    c = df["Close"].values.astype(np.float64)
    ema8  = calc_ema(df, 8).values
    atr14 = calc_atr(df, 14).values

    body_abs = np.abs(c - o)
    avg5 = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng = h - l
    body_pct = np.where(rng > 0, body_abs / rng, 0)
    upper3 = c >= h - rng/3
    lower3 = c <= l + rng/3
    ema_buy  = (c > ema8) if use_ema else True
    ema_sell = (c < ema8) if use_ema else True
    trig_buy  = (c > o) & (body_pct >= body_min) & (body_abs > avg5) & (rng >= min_range_x*spread_price) & upper3 & ema_buy
    trig_sell = (c < o) & (body_pct >= body_min) & (body_abs > avg5) & (rng >= min_range_x*spread_price) & lower3 & ema_sell

    trades_usd = []
    trade_bars_held = []
    active, cooldown = None, -1

    for i in range(20, len(c) - 1):
        # Entry logic
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            atr = atr14[i]
            if not (atr > 0): continue
            entry_price = o[i+1]
            hard_sl_dist = atr * hard_sl_atr_mult
            if trig_buy[i]:
                active = {"dir":"BUY", "entry":entry_price,
                          "sl":entry_price - hard_sl_dist,
                          "bar":i+1, "held":0}
            else:
                active = {"dir":"SELL", "entry":entry_price,
                          "sl":entry_price + hard_sl_dist,
                          "bar":i+1, "held":0}
            continue

        # Management logic (run on every bar while trade open)
        if active is not None and i > active["bar"]:
            active["held"] += 1
            bh, bl = h[i], l[i]

            # 1) Check hard SL hit during this bar
            hit_sl = False
            if active["dir"] == "BUY" and bl <= active["sl"]:
                hit_sl = True
            elif active["dir"] == "SELL" and bh >= active["sl"]:
                hit_sl = True
            if hit_sl:
                price_pnl = active["sl"] - active["entry"] if active["dir"]=="BUY" else active["entry"] - active["sl"]
                price_pnl -= spread_price
                trades_usd.append(price_pnl * lot * contract)
                trade_bars_held.append(active["held"])
                cooldown = i + 1
                active = None
                continue

            # 2) Evaluate weak-market exit logic on this just-closed bar
            current_body = body_pct[i]
            close_now = c[i]
            is_weak = current_body < weak_threshold

            # Compute current profit in $
            if active["dir"] == "BUY":
                price_pnl = close_now - active["entry"]
            else:
                price_pnl = active["entry"] - close_now
            profit_usd = price_pnl * lot * contract

            if is_weak:
                if profit_usd >= be_tolerance_usd:
                    # In profit + weak -> close in profit (subtract spread)
                    price_pnl -= spread_price
                    trades_usd.append(price_pnl * lot * contract)
                    trade_bars_held.append(active["held"])
                    cooldown = i + 1
                    active = None
                elif profit_usd >= -be_tolerance_usd:
                    # At BE + weak -> close at BE (subtract spread)
                    price_pnl -= spread_price
                    trades_usd.append(price_pnl * lot * contract)
                    trade_bars_held.append(active["held"])
                    cooldown = i + 1
                    active = None
                # else: small/big loss -> hold
            # else: strong market -> hold

    if not trades_usd: return None
    wins = sum(1 for t in trades_usd if t > 0)
    losses = sum(1 for t in trades_usd if t < 0)
    be_trades = len(trades_usd) - wins - losses
    avg_win = np.mean([t for t in trades_usd if t > 0]) if wins else 0
    avg_loss = np.mean([t for t in trades_usd if t < 0]) if losses else 0

    return {
        "trades": len(trades_usd), "wins": wins, "losses": losses, "be": be_trades,
        "wr": (wins + be_trades) / len(trades_usd) * 100,   # wins + BE = "not a loss" feel
        "true_wr": wins / len(trades_usd) * 100,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "net_usd": sum(trades_usd),
        "avg_held_bars": np.mean(trade_bars_held),
    }


def sweep(name, symbol, spread, lot, contract, body_min=0.75, use_ema=True, min_range_x=25):
    if not connect(): return None
    mt5.symbol_select(symbol, True)
    df = fetch_candles(symbol, mt5.TIMEFRAME_M15, count=96*DAYS + 200)
    disconnect()
    if df.empty: return None
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

    print(f"\n{'='*100}")
    print(f"{name} MOMENTUM-EXIT BACKTEST | M15 | lot={lot} | spread=${spread}")
    print(f"{'='*100}")

    # Sweep weak threshold + BE tolerance
    rows = []
    for weak, be_tol, small_loss in itertools.product(
        [0.40, 0.50, 0.60],         # weak threshold (body < this = weak)
        [0.25, 0.50, 1.00],         # BE tolerance in $
        [3.0, 5.0, 10.0],           # small loss limit
    ):
        r = backtest(df, spread, lot, contract, body_min, use_ema, min_range_x,
                     weak, be_tol, small_loss)
        if r is None: continue
        r.update({"weak": weak, "be_tol": be_tol, "small_loss": small_loss,
                  "tpd": r["trades"]/days})
        rows.append(r)

    rows.sort(key=lambda r: r["net_usd"], reverse=True)
    print(f"\n{'Weak<':<6} {'BEtol':<6} {'SmLoss':<7} | {'Trades':<7} {'T/D':<5} {'WR%':<6} {'TrueWR':<7} {'AvgW':<8} {'AvgL':<8} {'Bars':<5} {'Net$':<10}")
    print("-"*100)
    for r in rows[:10]:
        print(f"{r['weak']:<6} ${r['be_tol']:<5} ${r['small_loss']:<6} | {r['trades']:<7} {r['tpd']:<5.2f} {r['wr']:<6.1f} {r['true_wr']:<7.1f} ${r['avg_win']:<6.2f} ${r['avg_loss']:<6.2f} {r['avg_held_bars']:<5.1f} ${r['net_usd']:+8.2f}")

    return rows[0] if rows else None


def main():
    gold_best = sweep("GOLD", "XAUUSD", spread=0.155, lot=0.01, contract=100,
                      body_min=0.75, use_ema=True, min_range_x=25)
    btc_best  = sweep("BTC",  "BTCUSD", spread=6.0,   lot=0.04, contract=1.0,
                      body_min=0.75, use_ema=False, min_range_x=5)

    print("\n" + "="*100)
    print("WINNERS (momentum-ride-and-escape)")
    print("="*100)
    if gold_best:
        b = gold_best
        print(f"GOLD: weak<{b['weak']} BEtol=${b['be_tol']} small_loss=${b['small_loss']}")
        print(f"      WR {b['wr']:.1f}% (true {b['true_wr']:.1f}%) | {b['tpd']:.1f} T/D | avg held {b['avg_held_bars']:.1f} bars (~{b['avg_held_bars']*15:.0f} min)")
        print(f"      avg win ${b['avg_win']:+.2f} | avg loss ${b['avg_loss']:-.2f} | net ${b['net_usd']:+.2f}/90d")
    if btc_best:
        b = btc_best
        print(f"BTC:  weak<{b['weak']} BEtol=${b['be_tol']} small_loss=${b['small_loss']}")
        print(f"      WR {b['wr']:.1f}% (true {b['true_wr']:.1f}%) | {b['tpd']:.1f} T/D | avg held {b['avg_held_bars']:.1f} bars (~{b['avg_held_bars']*15:.0f} min)")
        print(f"      avg win ${b['avg_win']:+.2f} | avg loss ${b['avg_loss']:-.2f} | net ${b['net_usd']:+.2f}/90d")


if __name__ == "__main__":
    main()