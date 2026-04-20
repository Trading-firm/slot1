"""
Quick backtest: gold scalper with fixed $5.60 profit target (no rr_ratio).
Compares against the current 1:1.5 R:R baseline.
"""
import os, sys, math, numpy as np, pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

SYMBOL       = "XAUUSD"
DAYS         = 90
SPREAD_PRICE = 0.155
FIXED_TP_USD = 5.60
LOT_SIZE     = 0.01
CONTRACT     = 100     # 100 oz per lot
# Winning scalper config (from sweep)
BODY_MIN     = 0.75
MIN_RANGE_X  = 25
USE_EMA      = True
SL_BUFFER    = 0.1


def run_backtest(df, mode: str, rr_ratio: float = 1.5):
    """
    mode: 'fixed' -> TP is fixed $ profit (FIXED_TP_USD / (LOT*CONTRACT) = $X price move)
          'rr'    -> TP is SL_dist * rr_ratio
    """
    o = df["Open"].values.astype(np.float64)
    h = df["High"].values.astype(np.float64)
    l = df["Low"].values.astype(np.float64)
    c = df["Close"].values.astype(np.float64)
    ema8  = calc_ema(df, 8).values
    atr14 = calc_atr(df, 14).values
    n = len(c)

    body_abs  = np.abs(c - o)
    avg5      = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng       = h - l
    body_pct  = np.where(rng > 0, body_abs / rng, 0)
    upper_3rd = c >= h - rng/3
    lower_3rd = c <= l + rng/3

    trig_buy  = (c > o) & (body_pct >= BODY_MIN) & (body_abs > avg5) & (rng >= MIN_RANGE_X*SPREAD_PRICE) & upper_3rd & (c > ema8 if USE_EMA else True)
    trig_sell = (c < o) & (body_pct >= BODY_MIN) & (body_abs > avg5) & (rng >= MIN_RANGE_X*SPREAD_PRICE) & lower_3rd & (c < ema8 if USE_EMA else True)

    fixed_price_move = FIXED_TP_USD / (LOT_SIZE * CONTRACT)   # = $5.60 for 0.01 lot

    trades_R, trades_usd, sl_dists, tp_dists = [], [], [], []
    active, cooldown = None, -1
    for i in range(20, n-1):
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            atr = atr14[i]
            if not (atr > 0): continue
            entry = o[i+1]
            if trig_buy[i]:
                sl_dist = c[i] - (l[i] - atr*SL_BUFFER)
                if sl_dist <= 0: continue
                tp_dist = fixed_price_move if mode == "fixed" else sl_dist * rr_ratio
                active = {"dir":"BUY", "sl":entry-sl_dist, "tp":entry+tp_dist,
                          "sl_dist":sl_dist, "tp_dist":tp_dist, "bar":i+1}
            else:
                sl_dist = (h[i] + atr*SL_BUFFER) - c[i]
                if sl_dist <= 0: continue
                tp_dist = fixed_price_move if mode == "fixed" else sl_dist * rr_ratio
                active = {"dir":"SELL", "sl":entry+sl_dist, "tp":entry-tp_dist,
                          "sl_dist":sl_dist, "tp_dist":tp_dist, "bar":i+1}
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
                trades_usd.append(pnl * LOT_SIZE * CONTRACT)
                trades_R.append(pnl / active["sl_dist"])
                sl_dists.append(active["sl_dist"])
                tp_dists.append(active["tp_dist"])
                cooldown = i + 2
                active = None

    if not trades_R: return None
    wins = sum(1 for r in trades_R if r > 0)
    losses = len(trades_R) - wins
    return {
        "trades": len(trades_R), "wins": wins, "losses": losses,
        "wr": wins/len(trades_R)*100,
        "exp_R": sum(trades_R)/len(trades_R),
        "net_R": sum(trades_R),
        "net_usd": sum(trades_usd),
        "avg_sl_usd": np.mean(sl_dists),
        "avg_tp_usd": np.mean(tp_dists),
        "avg_rr": np.mean(tp_dists) / np.mean(sl_dists),
    }


def main():
    if not connect(): return
    mt5.symbol_select(SYMBOL, True)
    df = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=96*DAYS + 200)
    disconnect()
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)
    print(f"Gold M15 | {len(df)} bars over {days} days | spread ${SPREAD_PRICE}")
    print()
    print(f"{'Mode':<25} {'Trades':<7} {'T/D':<5} {'WR%':<6} {'ExpR':<7} {'NetR':<7} {'$90d':<9} {'avg SL':<8} {'avg TP':<8} {'avg R:R':<8}")
    print("-"*95)
    for label, mode, rr in [
        ("Current 1:1.5 R:R",  "rr",    1.5),
        ("NEW: fixed $5.60 TP", "fixed", 0),
        ("Old 1:2.5 R:R (ref)", "rr",    2.5),
        ("1:1.0 R:R (ref)",     "rr",    1.0),
    ]:
        r = run_backtest(df, mode, rr)
        if r is None: print(f"{label:<25} NO TRADES"); continue
        print(f"{label:<25} {r['trades']:<7} {r['trades']/days:<5.2f} {r['wr']:<6.1f} {r['exp_R']:+7.3f} {r['net_R']:+7.2f} ${r['net_usd']:+8.2f} ${r['avg_sl_usd']:<7.2f} ${r['avg_tp_usd']:<7.2f} 1:{r['avg_rr']:<7.2f}")


if __name__ == "__main__":
    main()