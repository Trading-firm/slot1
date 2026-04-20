"""
scripts/gold_scalper_sweep.py
──────────────────────────────
Gold-only scalper sweep on Exness. Spread modeled honestly.
Optimized: indicators precomputed once, inline tight loop, JSON checkpointing.
"""
import os, sys, math, itertools, json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())

from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

SYMBOL       = "XAUUSD"
DAYS         = 90
MIN_TRADES   = 50
SPREAD_PRICE = 0.155
MIN_LOT_RISK_USD = 1.0   # $1 per $1 move at 0.01 lot

TIMEFRAMES = [
    (mt5.TIMEFRAME_M5,  "M5",  288),
    (mt5.TIMEFRAME_M15, "M15", 96),
    (mt5.TIMEFRAME_M30, "M30", 48),
]

BODY_MIN_PCTS  = [0.45, 0.55, 0.65, 0.75]
RR_RATIOS      = [1.0, 1.5, 2.0, 2.5]
EMA_FILTERS    = [True, False]
MIN_RANGE_X    = [8, 15, 25]

SESSION_MODES = {
    "24/5":     None,
    "london+us": [(8, 23)],
    "us-only":  [(13, 23)],
}


def in_session_mask(times, sessions):
    if sessions is None:
        return np.ones(len(times), dtype=bool)
    ts = pd.to_datetime(times) + pd.Timedelta(hours=1)
    h = ts.hour.values
    mask = np.zeros(len(times), dtype=bool)
    for s, e in sessions:
        mask |= (h >= s) & (h <= e)
    return mask


def precompute(df):
    return {
        "o": df["Open"].values.astype(np.float64),
        "h": df["High"].values.astype(np.float64),
        "l": df["Low"].values.astype(np.float64),
        "c": df["Close"].values.astype(np.float64),
        "ema8":  calc_ema(df, 8).values,
        "atr14": calc_atr(df, 14).values,
        "time":  df["time"].values,
    }


def run_one(ind, body_min_pct, rr_ratio, use_ema, min_range_x, sessions, sess_cache):
    o, h, l, c = ind["o"], ind["h"], ind["l"], ind["c"]
    ema8, atr14 = ind["ema8"], ind["atr14"]
    n = len(c)

    # body_lookback=5 averages
    body_abs = np.abs(c - o)
    avg5_body = pd.Series(body_abs).rolling(5).mean().shift(1).values  # avg of previous 5

    rng = h - l
    body_pct = np.where(rng > 0, body_abs / rng, 0)

    bull = c > o
    bear = c < o
    upper_third = (c >= h - rng / 3)
    lower_third = (c <= l + rng / 3)

    # Trigger arrays
    trig_buy = (
        bull
        & (body_pct >= body_min_pct)
        & (body_abs > avg5_body)
        & (rng >= min_range_x * SPREAD_PRICE)
        & upper_third
    )
    trig_sell = (
        bear
        & (body_pct >= body_min_pct)
        & (body_abs > avg5_body)
        & (rng >= min_range_x * SPREAD_PRICE)
        & lower_third
    )
    if use_ema:
        trig_buy  = trig_buy  & (c > ema8)
        trig_sell = trig_sell & (c < ema8)

    sess_mask = sess_cache  # precomputed per session

    trades_R = []
    trades_pl = []
    active = None
    cooldown_until = -1

    for i in range(20, n - 1):
        if active is None and i > cooldown_until:
            if not sess_mask[i + 1]:
                continue
            if not (trig_buy[i] or trig_sell[i]):
                continue
            atr = atr14[i]
            if not (atr > 0):
                continue
            entry = o[i + 1]
            if trig_buy[i]:
                # Structural SL = trigger candle low - 0.1 ATR
                sl_dist = (c[i] - (l[i] - atr * 0.1))   # original sl_dist relative to close
                if sl_dist <= 0: continue
                sl_price = entry - sl_dist
                tp_price = entry + sl_dist * rr_ratio
                tp_dist  = sl_dist * rr_ratio
                direction = "BUY"
            else:
                sl_dist = ((h[i] + atr * 0.1) - c[i])
                if sl_dist <= 0: continue
                sl_price = entry + sl_dist
                tp_price = entry - sl_dist * rr_ratio
                tp_dist  = sl_dist * rr_ratio
                direction = "SELL"
            active = {
                "dir": direction,
                "sl": sl_price, "tp": tp_price,
                "sl_dist": sl_dist, "tp_dist": tp_dist,
                "bar": i + 1,
            }

        if active is not None and i + 1 > active["bar"]:
            bh, bl = h[i + 1], l[i + 1]
            hit_sl = hit_tp = False
            if active["dir"] == "BUY":
                if bl <= active["sl"]:    hit_sl = True
                elif bh >= active["tp"]:  hit_tp = True
            else:
                if bh >= active["sl"]:    hit_sl = True
                elif bl <= active["tp"]:  hit_tp = True
            if hit_sl or hit_tp:
                pnl = active["tp_dist"] - SPREAD_PRICE if hit_tp else -(active["sl_dist"] + SPREAD_PRICE)
                trades_pl.append(pnl)
                trades_R.append(pnl / active["sl_dist"])
                cooldown_until = i + 2
                active = None

    if not trades_R:
        return None
    wins = sum(1 for r in trades_R if r > 0)
    return {
        "trades":   len(trades_R),
        "wins":     wins,
        "losses":   len(trades_R) - wins,
        "wr":       round(wins / len(trades_R) * 100, 2),
        "exp_R":    round(sum(trades_R) / len(trades_R), 3),
        "net_R":    round(sum(trades_R), 2),
        "net_usd":  round(sum(trades_pl) * MIN_LOT_RISK_USD, 2),
    }


def main():
    if not connect():
        print("MT5 connect failed"); return
    mt5.symbol_select(SYMBOL, True)

    print("=" * 110)
    print(f"GOLD SCALPER SWEEP - {DAYS} days, spread=${SPREAD_PRICE}, lot=0.01")
    n_combos = len(BODY_MIN_PCTS) * len(RR_RATIOS) * len(EMA_FILTERS) * len(MIN_RANGE_X) * len(SESSION_MODES)
    print(f"Configs per TF: {n_combos} | Total runs: {n_combos * len(TIMEFRAMES)}")
    print("=" * 110)

    all_rows = []
    for tf, tf_name, bpd in TIMEFRAMES:
        print(f"\n--- {tf_name} ({bpd*DAYS+200} bars) ---")
        df = fetch_candles(SYMBOL, tf, count=bpd * DAYS + 200)
        if df.empty:
            print("  no data"); continue
        days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)
        ind = precompute(df)
        sess_caches = {name: in_session_mask(ind["time"], sess) for name, sess in SESSION_MODES.items()}

        for body, rr, ema, mr, sess_name in itertools.product(
            BODY_MIN_PCTS, RR_RATIOS, EMA_FILTERS, MIN_RANGE_X, SESSION_MODES.keys()
        ):
            r = run_one(ind, body, rr, ema, mr, SESSION_MODES[sess_name], sess_caches[sess_name])
            if r is None: continue
            r.update({
                "tf": tf_name, "body": body, "rr": rr, "ema": ema, "mr": mr,
                "sess": sess_name, "tpd": round(r["trades"] / days, 2),
            })
            r["score"] = round(r["exp_R"] * math.sqrt(r["trades"]), 3)
            all_rows.append(r)
        print(f"  {len(all_rows)} cumulative valid runs")

    disconnect()

    # Save raw results
    out_path = os.path.join(os.getcwd(), "scripts", "gold_scalper_results.json")
    with open(out_path, "w") as f:
        json.dump(all_rows, f, indent=2, default=str)
    print(f"\nRaw results saved to {out_path}")

    eligible = [r for r in all_rows if r["trades"] >= MIN_TRADES and r["exp_R"] > 0]
    eligible.sort(key=lambda r: r["score"], reverse=True)

    print("\n" + "=" * 110)
    print(f"TOP 15 GOLD SCALPER CONFIGS (>={MIN_TRADES} trades, positive expectancy)")
    print("=" * 110)
    print(f"{'TF':<4} {'Body':<5} {'R:R':<5} {'EMA':<6} {'MR':<3} {'Session':<10} | {'Trades':<7} {'T/D':<6} {'WR%':<6} {'Exp':<7} {'NetR':<7} {'$ at 0.01lot':<13}")
    print("-" * 110)
    for r in eligible[:15]:
        print(f"{r['tf']:<4} {r['body']:<5} {r['rr']:<5} {str(r['ema']):<6} {r['mr']:<3} {r['sess']:<10} | "
              f"{r['trades']:<7} {r['tpd']:<6} {r['wr']:<6} {r['exp_R']:+7.3f} {r['net_R']:+7.2f} ${r['net_usd']:+10.2f}")

    if not eligible:
        print("\nNO PROFITABLE CONFIG FOUND.")
        return

    b = eligible[0]
    print("\n" + "=" * 110)
    print(f"WINNER: {b['tf']} body={b['body']} R:R=1:{b['rr']} ema={b['ema']} mr={b['mr']} session={b['sess']}")
    print(f"  Win rate:   {b['wr']}%")
    print(f"  Trades/day: {b['tpd']} ({b['trades']} total over {DAYS}d)")
    print(f"  Expectancy: {b['exp_R']:+.3f}R per trade")
    print(f"  Net P/L at 0.01 lot: ${b['net_usd']:+,.2f} over {DAYS} days")
    print(f"\n  Projected on different account sizes (1% risk per trade, ~$5 avg SL):")
    avg_sl_usd = 5.0
    for bal in [200, 500, 1000, 5000]:
        risk_per_trade = bal * 0.01
        lot = max(0.01, round(risk_per_trade / (avg_sl_usd * 100), 2))
        scale = lot / 0.01
        projected = b['net_usd'] * scale
        print(f"    ${bal:>5} bal, lot {lot:.2f} (~${risk_per_trade:.2f}/trade) -> ${projected:+,.2f} over {DAYS}d ({projected/bal*100:+.1f}%)")
    print("=" * 110)


if __name__ == "__main__":
    main()