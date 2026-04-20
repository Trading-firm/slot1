"""
scripts/trend_scalper_backtest.py
──────────────────────────────────
Trend-aware momentum scalper:
  Entry: strong candle (body>=0.75) AND trend matches direction
  Exit:
    - Trend still strong in our direction  -> HOLD (ride it out)
    - Trend flipped against us             -> CLOSE (hard exit)
    - Trend weak + candle weak + profit/BE -> CLOSE (lock in / escape)
    - Trend weak + small loss              -> WAIT (recovery expected)
    - Hard SL (structural)                 -> broker catches

Trend = price vs EMA50/200 + ADX.
"""
import os, sys, math, itertools
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr, calc_adx

DAYS = 90


def backtest(df, spread_price, lot, contract, body_min, use_ema_fast, min_range_x,
             weak_threshold, be_tol_usd, small_loss_usd,
             adx_min, hard_sl_atr_mult=2.0, trend_filter=True):
    o = df["Open"].values.astype(np.float64)
    h = df["High"].values.astype(np.float64)
    l = df["Low"].values.astype(np.float64)
    c = df["Close"].values.astype(np.float64)
    ema8   = calc_ema(df, 8).values
    ema50  = calc_ema(df, 50).values
    ema200 = calc_ema(df, 200).values
    adx    = calc_adx(df, 14).values
    atr14  = calc_atr(df, 14).values

    body_abs = np.abs(c - o)
    avg5 = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng = h - l
    body_pct = np.where(rng > 0, body_abs / rng, 0)
    upper3 = c >= h - rng/3
    lower3 = c <= l + rng/3
    ema_buy  = (c > ema8) if use_ema_fast else True
    ema_sell = (c < ema8) if use_ema_fast else True

    # Trend detection — vectorized
    trend_up = (c > ema50) & (ema50 > ema200) & (adx >= adx_min)
    trend_dn = (c < ema50) & (ema50 < ema200) & (adx >= adx_min)

    trig_buy_base  = (c > o) & (body_pct >= body_min) & (body_abs > avg5) & (rng >= min_range_x*spread_price) & upper3 & ema_buy
    trig_sell_base = (c < o) & (body_pct >= body_min) & (body_abs > avg5) & (rng >= min_range_x*spread_price) & lower3 & ema_sell

    if trend_filter:
        trig_buy  = trig_buy_base  & trend_up
        trig_sell = trig_sell_base & trend_dn
    else:
        trig_buy, trig_sell = trig_buy_base, trig_sell_base

    trades_usd = []
    bars_held = []
    active, cooldown = None, -1

    for i in range(210, len(c) - 1):   # start after EMA200 warmup
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            if not (atr14[i] > 0): continue
            entry = o[i+1]
            hard_sl_dist = atr14[i] * hard_sl_atr_mult
            if trig_buy[i]:
                active = {"dir":"BUY","entry":entry,"sl":entry-hard_sl_dist,"bar":i+1,"held":0}
            else:
                active = {"dir":"SELL","entry":entry,"sl":entry+hard_sl_dist,"bar":i+1,"held":0}
            continue

        if active is not None and i > active["bar"]:
            active["held"] += 1
            bh, bl = h[i], l[i]

            # 1) Hard SL hit?
            hit_sl = (active["dir"]=="BUY" and bl <= active["sl"]) or \
                     (active["dir"]=="SELL" and bh >= active["sl"])
            if hit_sl:
                price_pnl = (active["sl"] - active["entry"]) if active["dir"]=="BUY" else (active["entry"] - active["sl"])
                price_pnl -= spread_price
                trades_usd.append(price_pnl * lot * contract)
                bars_held.append(active["held"])
                cooldown = i + 1
                active = None
                continue

            # Compute current profit
            close_now = c[i]
            price_pnl = (close_now - active["entry"]) if active["dir"]=="BUY" else (active["entry"] - close_now)
            profit_usd = price_pnl * lot * contract

            # 2) Trend flipped against us? Exit.
            trend_against = False
            if trend_filter:
                if active["dir"] == "BUY" and trend_dn[i]:  trend_against = True
                if active["dir"] == "SELL" and trend_up[i]: trend_against = True
            if trend_against:
                price_pnl -= spread_price
                trades_usd.append(price_pnl * lot * contract)
                bars_held.append(active["held"])
                cooldown = i + 1
                active = None
                continue

            # 3) Trend still in our favor? Hold regardless of candle.
            trend_with_us = False
            if trend_filter:
                if active["dir"] == "BUY" and trend_up[i]:  trend_with_us = True
                if active["dir"] == "SELL" and trend_dn[i]: trend_with_us = True
            if trend_with_us:
                continue

            # 4) Weak trend + evaluate candle strength
            is_weak = body_pct[i] < weak_threshold
            if is_weak:
                if profit_usd >= be_tol_usd:
                    price_pnl -= spread_price
                    trades_usd.append(price_pnl * lot * contract)
                    bars_held.append(active["held"])
                    cooldown = i + 1
                    active = None
                elif profit_usd >= -be_tol_usd:
                    price_pnl -= spread_price
                    trades_usd.append(price_pnl * lot * contract)
                    bars_held.append(active["held"])
                    cooldown = i + 1
                    active = None
                # else: small/big loss -> hold

    if not trades_usd: return None
    wins = sum(1 for t in trades_usd if t > 0)
    losses = sum(1 for t in trades_usd if t < 0)
    avg_win = np.mean([t for t in trades_usd if t > 0]) if wins else 0
    avg_loss = np.mean([t for t in trades_usd if t < 0]) if losses else 0
    return {
        "trades": len(trades_usd), "wins": wins, "losses": losses,
        "wr": (wins / len(trades_usd) * 100) if trades_usd else 0,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "net_usd": sum(trades_usd),
        "avg_held": np.mean(bars_held) if bars_held else 0,
    }


def main():
    for name, sym, spread, lot, contract, use_ema_f, mr in [
        ("GOLD", "XAUUSD", 0.155, 0.01, 100, True,  25),
        ("BTC",  "BTCUSD", 6.0,   0.04, 1.0, False, 5),
    ]:
        if not connect(): return
        mt5.symbol_select(sym, True)
        df = fetch_candles(sym, mt5.TIMEFRAME_M15, count=96*DAYS + 500)
        disconnect()
        if df.empty: continue
        days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

        print(f"\n{'='*100}")
        print(f"{name} M15 | lot={lot} | spread=${spread}  — compare NO-trend vs WITH-trend")
        print(f"{'='*100}")

        for tf_label, tf in [("NO trend filter", False), ("WITH trend filter", True)]:
            print(f"\n--- {tf_label} ---")
            print(f"{'WeakB':<6} {'BEtol':<6} {'ADX>=':<6} | {'Trades':<7} {'T/D':<5} {'WR%':<6} {'AvgW':<8} {'AvgL':<8} {'Bars':<5} {'Net$':<10}")
            print("-"*95)
            results = []
            weak_vals = [0.40, 0.50, 0.60]
            adx_vals  = [15, 20, 25] if tf else [20]
            for weak, adx_min in itertools.product(weak_vals, adx_vals):
                r = backtest(df, spread, lot, contract, 0.75, use_ema_f, mr,
                             weak, 0.50 if name=="GOLD" else 0.25, 3.0,
                             adx_min, trend_filter=tf)
                if r is None: continue
                r["weak"], r["adx"] = weak, adx_min
                r["tpd"] = r["trades"] / days
                results.append(r)
            results.sort(key=lambda r: r["net_usd"], reverse=True)
            for r in results[:5]:
                print(f"{r['weak']:<6} ${0.50 if name=='GOLD' else 0.25:<5} {r['adx']:<6} | {r['trades']:<7} {r['tpd']:<5.2f} {r['wr']:<6.1f} ${r['avg_win']:<6.2f} ${r['avg_loss']:<6.2f} {r['avg_held']:<5.1f} ${r['net_usd']:+8.2f}")


if __name__ == "__main__":
    main()