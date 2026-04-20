"""
BTCUSD scalper sweep. Same structure as gold_scalper_sweep.py,
different symbol + spread. Optimized with vectorized triggers.
"""
import os, sys, math, itertools, json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

SYMBOL       = "BTCUSD"
DAYS         = 90
MIN_TRADES   = 50
SPREAD_PRICE = 6.0      # Exness Raw-ish spread
MIN_LOT_RISK = 0.01     # $1 move = $0.01 P/L on 0.01 lot

TIMEFRAMES = [
    (mt5.TIMEFRAME_M5,  "M5",  288),
    (mt5.TIMEFRAME_M15, "M15", 96),
    (mt5.TIMEFRAME_M30, "M30", 48),
]

BODY_MIN_PCTS  = [0.45, 0.55, 0.65, 0.75]
RR_RATIOS      = [1.0, 1.5, 2.0, 2.5]
EMA_FILTERS    = [True, False]
MIN_RANGE_X    = [5, 10, 20]


def precompute(df):
    return {
        "o": df["Open"].values.astype(np.float64),
        "h": df["High"].values.astype(np.float64),
        "l": df["Low"].values.astype(np.float64),
        "c": df["Close"].values.astype(np.float64),
        "ema8":  calc_ema(df, 8).values,
        "atr14": calc_atr(df, 14).values,
    }


def run_one(ind, body_min_pct, rr_ratio, use_ema, min_range_x):
    o, h, l, c = ind["o"], ind["h"], ind["l"], ind["c"]
    ema8, atr14 = ind["ema8"], ind["atr14"]
    n = len(c)
    body_abs = np.abs(c - o)
    avg5_body = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng = h - l
    body_pct = np.where(rng > 0, body_abs / rng, 0)
    bull = c > o; bear = c < o
    upper_third = c >= h - rng/3
    lower_third = c <= l + rng/3

    trig_buy  = bull & (body_pct >= body_min_pct) & (body_abs > avg5_body) & (rng >= min_range_x*SPREAD_PRICE) & upper_third
    trig_sell = bear & (body_pct >= body_min_pct) & (body_abs > avg5_body) & (rng >= min_range_x*SPREAD_PRICE) & lower_third
    if use_ema:
        trig_buy  = trig_buy  & (c > ema8)
        trig_sell = trig_sell & (c < ema8)

    trades_R, trades_usd = [], []
    active, cooldown = None, -1
    for i in range(20, n-1):
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            atr = atr14[i]
            if not (atr > 0): continue
            entry = o[i+1]
            if trig_buy[i]:
                sl_dist = c[i] - (l[i] - atr*0.1)
                if sl_dist <= 0: continue
                active = {"dir":"BUY","sl":entry-sl_dist,"tp":entry+sl_dist*rr_ratio,
                          "sl_dist":sl_dist,"tp_dist":sl_dist*rr_ratio,"bar":i+1}
            else:
                sl_dist = (h[i] + atr*0.1) - c[i]
                if sl_dist <= 0: continue
                active = {"dir":"SELL","sl":entry+sl_dist,"tp":entry-sl_dist*rr_ratio,
                          "sl_dist":sl_dist,"tp_dist":sl_dist*rr_ratio,"bar":i+1}
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
                pnl = active["tp_dist"] - SPREAD_PRICE if hit_tp else -(active["sl_dist"] + SPREAD_PRICE)
                trades_usd.append(pnl)
                trades_R.append(pnl / active["sl_dist"])
                cooldown = i + 2
                active = None

    if not trades_R: return None
    wins = sum(1 for r in trades_R if r > 0)
    return {
        "trades": len(trades_R), "wins": wins, "losses": len(trades_R)-wins,
        "wr": round(wins/len(trades_R)*100, 2),
        "exp_R": round(sum(trades_R)/len(trades_R), 3),
        "net_R": round(sum(trades_R), 2),
        "net_usd_001lot": round(sum(trades_usd) * MIN_LOT_RISK, 2),
    }


def main():
    if not connect(): print("fail"); return
    mt5.symbol_select(SYMBOL, True)
    print("="*100)
    print(f"BTCUSD SCALPER SWEEP - {DAYS} days, spread=${SPREAD_PRICE}")
    print("="*100)

    rows = []
    for tf, tf_name, bpd in TIMEFRAMES:
        df = fetch_candles(SYMBOL, tf, count=bpd*DAYS + 200)
        if df.empty: print(f"{tf_name}: no data"); continue
        days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)
        print(f"{tf_name}: {len(df)} bars over {days} days")
        ind = precompute(df)
        for body, rr, ema, mr in itertools.product(BODY_MIN_PCTS, RR_RATIOS, EMA_FILTERS, MIN_RANGE_X):
            r = run_one(ind, body, rr, ema, mr)
            if r is None: continue
            r.update({"tf":tf_name, "body":body, "rr":rr, "ema":ema, "mr":mr,
                      "tpd": round(r["trades"]/days, 2),
                      "score": round(r["exp_R"] * math.sqrt(r["trades"]), 3)})
            rows.append(r)
    disconnect()

    elig = [r for r in rows if r["trades"] >= MIN_TRADES and r["exp_R"] > 0]
    elig.sort(key=lambda r: r["score"], reverse=True)

    print("\n"+"="*100)
    print(f"TOP 15 BTCUSD CONFIGS (>={MIN_TRADES} trades, positive expectancy)")
    print("="*100)
    print(f"{'TF':<4} {'Body':<5} {'R:R':<5} {'EMA':<6} {'MR':<3} | {'Tr':<4} {'T/D':<5} {'WR%':<6} {'Exp':<7} {'NetR':<7} {'$@0.01lot':<10}")
    print("-"*100)
    for r in elig[:15]:
        print(f"{r['tf']:<4} {r['body']:<5} {r['rr']:<5} {str(r['ema']):<6} {r['mr']:<3} | "
              f"{r['trades']:<4} {r['tpd']:<5} {r['wr']:<6} {r['exp_R']:+7.3f} {r['net_R']:+7.2f} ${r['net_usd_001lot']:+9.2f}")

    if elig:
        b = elig[0]
        print(f"\nWINNER: {b['tf']} body={b['body']} rr=1:{b['rr']} ema={b['ema']} mr={b['mr']}")
        print(f"  {b['trades']} trades, {b['tpd']}/day, WR {b['wr']}%, Exp {b['exp_R']:+.3f}R, Net ${b['net_usd_001lot']:+,.2f} @ 0.01 lot")
    else:
        print("\nNO PROFITABLE CONFIG FOUND for BTCUSD.")

    with open(os.path.join(os.getcwd(), "scripts", "btc_scalper_results.json"), "w") as f:
        json.dump(rows, f, indent=2, default=str)


if __name__ == "__main__":
    main()