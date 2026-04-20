"""
Check user's current live config via honest 90-day backtest.
Tests: gold $9.60 monitor exit + BTC $10 monitor exit at 0.1 lot.
"""
import os, sys, numpy as np, pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr

DAYS        = 90
ACCOUNT_BAL = 200.00


def backtest(symbol, spread_price, lot, contract, body_min, use_ema, min_range_x,
             rr_ratio, monitor_target_usd):
    """Returns stats dict. monitor_target_usd=0 disables monitor (uses structural TP)."""
    if not connect(): return None
    mt5.symbol_select(symbol, True)
    bars_per_day = 96  # M15
    df = fetch_candles(symbol, mt5.TIMEFRAME_M15, count=bars_per_day * DAYS + 200)
    disconnect()
    if df.empty: return None
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

    o = df["Open"].values.astype(np.float64)
    h = df["High"].values.astype(np.float64)
    l = df["Low"].values.astype(np.float64)
    c = df["Close"].values.astype(np.float64)
    ema8  = calc_ema(df, 8).values
    atr14 = calc_atr(df, 14).values

    body_abs = np.abs(c - o)
    avg5     = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng      = h - l
    body_pct = np.where(rng > 0, body_abs / rng, 0)
    upper3   = c >= h - rng/3
    lower3   = c <= l + rng/3

    trig_buy  = (c > o) & (body_pct >= body_min) & (body_abs > avg5) & (rng >= min_range_x*spread_price) & upper3 & ((c > ema8) if use_ema else True)
    trig_sell = (c < o) & (body_pct >= body_min) & (body_abs > avg5) & (rng >= min_range_x*spread_price) & lower3 & ((c < ema8) if use_ema else True)

    # Monitor price move required to reach target profit
    monitor_price_move = (monitor_target_usd / (lot * contract)) if monitor_target_usd > 0 else 0

    trades_usd = []
    sl_usds, tp_usds = [], []
    active, cooldown = None, -1
    for i in range(20, len(c) - 1):
        if active is None and i > cooldown:
            if not (trig_buy[i] or trig_sell[i]): continue
            atr = atr14[i]
            if not (atr > 0): continue
            entry = o[i+1]
            if trig_buy[i]:
                sl_dist = c[i] - (l[i] - atr*0.1)
                if sl_dist <= 0: continue
                structural_tp = sl_dist * rr_ratio
                tp_dist = min(monitor_price_move, structural_tp) if monitor_price_move > 0 else structural_tp
                active = {"dir":"BUY","sl":entry-sl_dist,"tp":entry+tp_dist,"sl_dist":sl_dist,"tp_dist":tp_dist,"bar":i+1}
            else:
                sl_dist = (h[i] + atr*0.1) - c[i]
                if sl_dist <= 0: continue
                structural_tp = sl_dist * rr_ratio
                tp_dist = min(monitor_price_move, structural_tp) if monitor_price_move > 0 else structural_tp
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
                price_pnl = active["tp_dist"] - spread_price if hit_tp else -(active["sl_dist"] + spread_price)
                trade_usd = price_pnl * lot * contract
                trades_usd.append(trade_usd)
                sl_usds.append(active["sl_dist"] * lot * contract)
                tp_usds.append(active["tp_dist"] * lot * contract)
                cooldown = i + 2
                active = None

    if not trades_usd: return None
    wins = sum(1 for t in trades_usd if t > 0)
    losses = len(trades_usd) - wins
    avg_sl = np.mean(sl_usds)
    avg_tp = np.mean(tp_usds)
    pct_risk = avg_sl / ACCOUNT_BAL * 100
    return {
        "trades": len(trades_usd), "wins": wins, "losses": losses,
        "wr": wins/len(trades_usd)*100,
        "tpd": len(trades_usd)/days,
        "net_usd": sum(trades_usd),
        "avg_loss_usd": avg_sl,
        "avg_win_usd": avg_tp,
        "rr": avg_tp / avg_sl,
        "pct_risk": pct_risk,
        "max_loss_streak": _max_loss_streak(trades_usd),
        "max_dd": _max_drawdown(trades_usd),
    }


def _max_loss_streak(trades):
    cur, best = 0, 0
    for t in trades:
        cur = cur + 1 if t <= 0 else 0
        best = max(best, cur)
    return best


def _max_drawdown(trades):
    equity, peak, dd = 0, 0, 0
    for t in trades:
        equity += t
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return dd


def show(label, r):
    if r is None:
        print(f"{label:<50} NO DATA"); return
    verdict = "OK" if r['net_usd'] > 0 and r['pct_risk'] <= 3 else ("RISKY" if r['net_usd'] > 0 else "LOSING")
    print(f"\n=== {label} ===")
    print(f"  Trades:        {r['trades']} over 90d  ({r['tpd']:.1f}/day)")
    print(f"  Win Rate:      {r['wr']:.1f}%  ({r['wins']}W / {r['losses']}L)")
    print(f"  Avg win:       ${r['avg_win_usd']:+.2f}")
    print(f"  Avg loss:      ${r['avg_loss_usd']:-.2f}")
    print(f"  R:R in $:      1:{r['rr']:.2f}")
    print(f"  Risk/trade:    {r['pct_risk']:.1f}% of ${ACCOUNT_BAL} account")
    print(f"  Max losing streak: {r['max_loss_streak']} trades in a row")
    print(f"  Max drawdown: ${r['max_dd']:+.2f}")
    print(f"  Net 90d:       ${r['net_usd']:+,.2f}  ({r['net_usd']/ACCOUNT_BAL*100:+.1f}% return)")
    print(f"  VERDICT:       {verdict}")


def main():
    print(f"ACCOUNT: ${ACCOUNT_BAL}  |  Testing USER'S CURRENT CONFIG")
    print("="*80)

    # User's gold config: 0.01 lot, 1:1.5 RR, EMA on, mr=25, monitor $9.60
    r_gold = backtest(
        symbol="XAUUSD", spread_price=0.155, lot=0.01, contract=100,
        body_min=0.75, use_ema=True, min_range_x=25,
        rr_ratio=1.5, monitor_target_usd=9.60,
    )
    show("GOLD @ 0.01 lot, monitor exit $9.60", r_gold)

    # User's BTC config: 0.1 lot, 1:1.0 RR, EMA off, mr=5, monitor $10
    r_btc = backtest(
        symbol="BTCUSD", spread_price=6.0, lot=0.1, contract=1.0,
        body_min=0.75, use_ema=False, min_range_x=5,
        rr_ratio=1.0, monitor_target_usd=10.00,
    )
    show("BTC @ 0.1 lot, monitor exit $10.00", r_btc)

    # Reference: safer sizing
    print("\n\n" + "="*80)
    print("FOR COMPARISON — SAFER ALTERNATIVES")
    print("="*80)

    r_gold_safe = backtest(
        symbol="XAUUSD", spread_price=0.155, lot=0.01, contract=100,
        body_min=0.75, use_ema=True, min_range_x=25,
        rr_ratio=1.5, monitor_target_usd=0,
    )
    show("GOLD @ 0.01 lot, NO monitor (structural TP at 1:1.5)", r_gold_safe)

    r_btc_safe = backtest(
        symbol="BTCUSD", spread_price=6.0, lot=0.01, contract=1.0,
        body_min=0.75, use_ema=False, min_range_x=5,
        rr_ratio=1.0, monitor_target_usd=0,
    )
    show("BTC @ 0.01 lot, NO monitor (structural TP at 1:1.0)", r_btc_safe)


if __name__ == "__main__":
    main()