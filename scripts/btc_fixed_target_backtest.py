"""
Quick backtest: BTC scalper with fixed $2 profit target vs current 1:1.5 R:R.
"""
import os, sys, numpy as np, pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

SYMBOL       = "BTCUSD"
DAYS         = 90
SPREAD_PRICE = 6.0
LOT_SIZE     = 0.01
CONTRACT     = 1.0
FIXED_TP_USD = 2.00
BODY_MIN     = 0.75
MIN_RANGE_X  = 5
USE_EMA      = False
SL_BUFFER    = 0.1


def run(df, mode, rr_ratio=1.5):
    o, h, l, c = (df[k].values.astype(np.float64) for k in ["Open","High","Low","Close"])
    ema8, atr14 = calc_ema(df, 8).values, calc_atr(df, 14).values
    body_abs = np.abs(c - o)
    avg5 = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng = h - l
    body_pct = np.where(rng > 0, body_abs / rng, 0)
    upper_3rd = c >= h - rng/3
    lower_3rd = c <= l + rng/3
    ema_ok_buy  = (c > ema8) if USE_EMA else True
    ema_ok_sell = (c < ema8) if USE_EMA else True
    trig_buy  = (c > o) & (body_pct >= BODY_MIN) & (body_abs > avg5) & (rng >= MIN_RANGE_X*SPREAD_PRICE) & upper_3rd & ema_ok_buy
    trig_sell = (c < o) & (body_pct >= BODY_MIN) & (body_abs > avg5) & (rng >= MIN_RANGE_X*SPREAD_PRICE) & lower_3rd & ema_ok_sell

    fixed_price_move = FIXED_TP_USD / (LOT_SIZE * CONTRACT)   # $200 price move for 0.01 lot BTC

    trades_usd, sl_prices, tp_prices = [], [], []
    active, cooldown = None, -1
    for i in range(20, len(c) - 1):
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            atr = atr14[i]
            if not (atr > 0): continue
            entry = o[i+1]
            if trig_buy[i]:
                sl_dist = c[i] - (l[i] - atr*SL_BUFFER)
                if sl_dist <= 0: continue
                tp_dist = fixed_price_move if mode == "fixed" else sl_dist * rr_ratio
                active = {"dir":"BUY","sl":entry-sl_dist,"tp":entry+tp_dist,"sl_dist":sl_dist,"tp_dist":tp_dist,"bar":i+1}
            else:
                sl_dist = (h[i] + atr*SL_BUFFER) - c[i]
                if sl_dist <= 0: continue
                tp_dist = fixed_price_move if mode == "fixed" else sl_dist * rr_ratio
                active = {"dir":"SELL","sl":entry+sl_dist,"tp":entry-tp_dist,"sl_dist":sl_dist,"tp_dist":tp_dist,"bar":i+1}
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
                price_pnl = active["tp_dist"] - SPREAD_PRICE if hit_tp else -(active["sl_dist"] + SPREAD_PRICE)
                trades_usd.append(price_pnl * LOT_SIZE * CONTRACT)
                sl_prices.append(active["sl_dist"])
                tp_prices.append(active["tp_dist"])
                cooldown = i + 2
                active = None

    if not trades_usd: return None
    wins = sum(1 for t in trades_usd if t > 0)
    losses = len(trades_usd) - wins
    return {
        "trades": len(trades_usd), "wins": wins, "losses": losses,
        "wr": wins/len(trades_usd)*100,
        "net_usd": sum(trades_usd),
        "avg_sl_$": np.mean(sl_prices) * LOT_SIZE * CONTRACT,
        "avg_tp_$": np.mean(tp_prices) * LOT_SIZE * CONTRACT,
    }


def main():
    if not connect(): return
    mt5.symbol_select(SYMBOL, True)
    df = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=96*DAYS + 200)
    disconnect()
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)
    print(f"BTCUSD M15 | {len(df)} bars over {days} days | spread ${SPREAD_PRICE} | lot {LOT_SIZE}")
    print()
    print(f"{'Mode':<24} {'Trades':<7} {'T/D':<5} {'WR%':<6} {'NetUSD':<9} {'Avg SL$':<9} {'Avg TP$':<9} {'R:R$':<8}")
    print("-"*85)
    for label, mode, rr in [
        ("Current 1:1.5 R:R",    "rr", 1.5),
        ("NEW: fixed $2.00 TP",   "fixed", 0),
        ("1:1.0 R:R",             "rr", 1.0),
        ("1:2.0 R:R",             "rr", 2.0),
    ]:
        r = run(df, mode, rr)
        if r is None:
            print(f"{label:<24} NO TRADES"); continue
        avg_rr = r['avg_tp_$'] / r['avg_sl_$']
        print(f"{label:<24} {r['trades']:<7} {r['trades']/days:<5.2f} {r['wr']:<6.1f} ${r['net_usd']:+7.2f}  ${r['avg_sl_$']:<7.2f} ${r['avg_tp_$']:<7.2f} 1:{avg_rr:<7.2f}")


if __name__ == "__main__":
    main()