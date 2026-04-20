"""
scripts/fixed_scalper_sweep.py
────────────────────────────────
Proper scalping backtest — fixed-$ SL and TP (not structural).
Per the user's scalping vision: enter on strong momentum, tight SL, small TP, exit fast.

Tests multiple SL/TP combinations per market, spread cost modeled.
Reports WR, expectancy, net $ at the configured lot size.
"""
import os, sys, math, itertools, json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

DAYS = 90
MIN_TRADES = 50


def run_fixed(df, spread_price, body_min, use_ema, min_range_x,
              sl_usd_target, tp_usd_target, lot, contract):
    """Fixed-$ SL/TP backtest. Returns stats."""
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

    # Fixed price distances
    sl_price_move = sl_usd_target / (lot * contract)
    tp_price_move = tp_usd_target / (lot * contract)

    trades_usd = []
    active, cooldown = None, -1
    for i in range(20, len(c) - 1):
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            if not (atr14[i] > 0): continue
            entry = o[i+1]
            if trig_buy[i]:
                active = {"dir":"BUY","sl":entry-sl_price_move,"tp":entry+tp_price_move,"bar":i+1}
            else:
                active = {"dir":"SELL","sl":entry+sl_price_move,"tp":entry-tp_price_move,"bar":i+1}
        if active is not None and i+1 > active["bar"]:
            bh, bl = h[i+1], l[i+1]
            hit_sl = hit_tp = False
            if active["dir"] == "BUY":
                if bl <= active["sl"]: hit_sl = True
                elif bh >= active["tp"]: hit_tp = True
            else:
                if bh >= active["sl"]: hit_sl = True
                elif bl <= active["tp"]: hit_tp = True
            if hit_sl or hit_tp:
                # P/L in price units, then convert to $
                price_pnl = tp_price_move - spread_price if hit_tp else -(sl_price_move + spread_price)
                trades_usd.append(price_pnl * lot * contract)
                cooldown = i + 2
                active = None

    if not trades_usd: return None
    wins = sum(1 for t in trades_usd if t > 0)
    return {
        "trades": len(trades_usd), "wins": wins, "losses": len(trades_usd)-wins,
        "wr": wins/len(trades_usd)*100,
        "net_usd": sum(trades_usd),
        "avg_win":  np.mean([t for t in trades_usd if t > 0]) if wins else 0,
        "avg_loss": np.mean([t for t in trades_usd if t <= 0]) if (len(trades_usd)-wins) else 0,
    }


def sweep_market(name, symbol, spread, lot, contract, sl_options, tp_options,
                 body_min=0.75, use_ema=True, min_range_x=25):
    print(f"\n{'='*100}")
    print(f"{name} SWEEP | lot={lot} | contract={contract} | spread=${spread}")
    print(f"Entry: body>={body_min}, min_range>={min_range_x}x spread, EMA filter={use_ema}")
    print(f"{'='*100}")

    if not connect(): return None
    mt5.symbol_select(symbol, True)
    df = fetch_candles(symbol, mt5.TIMEFRAME_M15, count=96*DAYS + 200)
    disconnect()
    if df.empty: return None
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

    rows = []
    for sl_usd, tp_usd in itertools.product(sl_options, tp_options):
        r = run_fixed(df, spread, body_min, use_ema, min_range_x, sl_usd, tp_usd, lot, contract)
        if r is None: continue
        r.update({
            "sl_usd": sl_usd, "tp_usd": tp_usd, "rr": tp_usd/sl_usd,
            "tpd": r["trades"]/days,
            "score": (r["wr"]/100 * tp_usd - (1 - r["wr"]/100) * sl_usd) * r["trades"],
        })
        rows.append(r)

    # Rank by net profit primarily, filter min trades
    elig = [r for r in rows if r["trades"] >= MIN_TRADES]
    elig.sort(key=lambda r: r["net_usd"], reverse=True)

    print(f"\n{'SL$':<6} {'TP$':<6} {'R:R':<6} {'Trades':<7} {'T/D':<5} {'WR%':<6} {'AvgW$':<8} {'AvgL$':<8} {'Net$':<10}")
    print("-"*90)
    for r in elig[:15]:
        print(f"${r['sl_usd']:<5} ${r['tp_usd']:<5} 1:{r['rr']:<4.2f} {r['trades']:<7} {r['tpd']:<5.2f} {r['wr']:<6.1f} ${r['avg_win']:<6.2f} ${r['avg_loss']:<6.2f} ${r['net_usd']:+8.2f}")

    return elig[0] if elig else None


def main():
    winners = {}

    # ── Gold at 0.01 lot ──
    gold_best = sweep_market(
        "GOLD", "XAUUSD", spread=0.155, lot=0.01, contract=100,
        sl_options=[2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
        tp_options=[2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0],
        body_min=0.75, use_ema=True, min_range_x=25,
    )
    if gold_best: winners["XAUUSD"] = gold_best

    # ── BTC at 0.04 lot ──
    btc_best = sweep_market(
        "BTC", "BTCUSD", spread=6.0, lot=0.04, contract=1.0,
        sl_options=[3.0, 5.0, 7.0, 10.0, 15.0, 20.0],
        tp_options=[3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0],
        body_min=0.75, use_ema=False, min_range_x=5,
    )
    if btc_best: winners["BTCUSD"] = btc_best

    print("\n\n" + "="*100)
    print("RECOMMENDED CONFIG (winners by net $)")
    print("="*100)
    for sym, w in winners.items():
        print(f"{sym}: sl_usd=${w['sl_usd']} tp_usd=${w['tp_usd']} (R:R 1:{w['rr']:.2f})")
        print(f"  WR {w['wr']:.1f}% | {w['tpd']:.1f} T/D | avg win ${w['avg_win']:+.2f} | avg loss ${w['avg_loss']:-.2f} | net ${w['net_usd']:+.2f} / 90d")


if __name__ == "__main__":
    main()