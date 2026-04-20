"""
Test fixes for gold's 'enter at peak -> BE exit before continuation' problem.
Compares:
  CURRENT: weak=0.40, be_tol=$0.50, small_loss=$3 (current live)
  FIX A:   loosened thresholds (hold longer through pullbacks)
  FIX B:   add trend filter (only trade with trend)
  FIX C:   both A + B
"""
import os, sys, numpy as np, pandas as pd
import MetaTrader5 as mt5
sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_atr, calc_adx

DAYS = 90


def run(df, spread, lot, contract, body_min, use_ema_f, min_range_x,
        weak_t, be_tol, small_loss, trend_on, adx_min, hard_sl_mult=2.0):
    o,h,l,c = (df[k].values.astype(np.float64) for k in ["Open","High","Low","Close"])
    ema8   = calc_ema(df, 8).values
    ema50  = calc_ema(df, 50).values
    ema200 = calc_ema(df, 200).values
    atr14  = calc_atr(df, 14).values
    adx    = calc_adx(df, 14).values

    body_abs = np.abs(c-o); avg5 = pd.Series(body_abs).rolling(5).mean().shift(1).values
    rng = h-l; body_pct = np.where(rng>0, body_abs/rng, 0)
    up3 = c >= h-rng/3; lo3 = c <= l+rng/3
    eb = (c>ema8) if use_ema_f else True
    es = (c<ema8) if use_ema_f else True

    trend_up = (c>ema50) & (ema50>ema200) & (adx>=adx_min)
    trend_dn = (c<ema50) & (ema50<ema200) & (adx>=adx_min)

    tb = (c>o) & (body_pct>=body_min) & (body_abs>avg5) & (rng>=min_range_x*spread) & up3 & eb
    ts = (c<o) & (body_pct>=body_min) & (body_abs>avg5) & (rng>=min_range_x*spread) & lo3 & es
    if trend_on:
        tb &= trend_up
        ts &= trend_dn

    trades, held = [], []
    active, cd = None, -1
    for i in range(210, len(c)-1):
        if active is None and i > cd:
            if not (tb[i] or ts[i]): continue
            if not (atr14[i]>0): continue
            entry = o[i+1]
            hsd = atr14[i] * hard_sl_mult
            active = {"dir":"BUY" if tb[i] else "SELL", "entry":entry,
                      "sl": entry-hsd if tb[i] else entry+hsd, "bar":i+1, "h":0}
            continue
        if active and i > active["bar"]:
            active["h"] += 1
            bh, bl = h[i], l[i]
            hit = (active["dir"]=="BUY" and bl<=active["sl"]) or (active["dir"]=="SELL" and bh>=active["sl"])
            if hit:
                pp = (active["sl"]-active["entry"]) if active["dir"]=="BUY" else (active["entry"]-active["sl"])
                pp -= spread
                trades.append(pp*lot*contract); held.append(active["h"]); cd=i+1; active=None
                continue
            cn = c[i]
            pp = (cn-active["entry"]) if active["dir"]=="BUY" else (active["entry"]-cn)
            pusd = pp*lot*contract

            if trend_on:
                ta = (active["dir"]=="BUY" and trend_dn[i]) or (active["dir"]=="SELL" and trend_up[i])
                tw = (active["dir"]=="BUY" and trend_up[i]) or (active["dir"]=="SELL" and trend_dn[i])
                if ta:
                    pp -= spread
                    trades.append(pp*lot*contract); held.append(active["h"]); cd=i+1; active=None
                    continue
                if tw:
                    continue

            if body_pct[i] < weak_t:
                if pusd >= be_tol:
                    pp -= spread
                    trades.append(pp*lot*contract); held.append(active["h"]); cd=i+1; active=None
                elif pusd >= -be_tol:
                    pp -= spread
                    trades.append(pp*lot*contract); held.append(active["h"]); cd=i+1; active=None

    if not trades: return None
    w = sum(1 for t in trades if t>0); los = sum(1 for t in trades if t<0)
    return {
        "n": len(trades), "w": w, "l": los, "be": len(trades)-w-los,
        "wr": (w+len(trades)-w-los)/len(trades)*100,
        "true_wr": w/len(trades)*100,
        "aw": np.mean([t for t in trades if t>0]) if w else 0,
        "al": np.mean([t for t in trades if t<0]) if los else 0,
        "net": sum(trades), "avg_h": np.mean(held),
    }


def main():
    if not connect(): return
    mt5.symbol_select("XAUUSD", True)
    df = fetch_candles("XAUUSD", mt5.TIMEFRAME_M15, count=96*DAYS+500)
    disconnect()
    days = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

    print(f"\nGOLD — fixes for peak-entry/BE-exit problem | M15 | $0.01 lot | {days}d")
    print(f"{'Config':<40} {'N':<5} {'T/D':<5} {'WR%':<6} {'True':<6} {'AvgW':<7} {'AvgL':<7} {'Hold':<5} {'Net$':<10}")
    print("-"*100)

    params = {"spread":0.155, "lot":0.01, "contract":100, "body_min":0.75,
              "use_ema_f":True, "min_range_x":25}

    cases = [
        ("CURRENT live (weak=0.40 be=$0.50 small=$3)",  0.40, 0.50, 3.00, False, 20),
        ("FIX A1: relax weak (weak=0.25 be=$1 small=$5)", 0.25, 1.00, 5.00, False, 20),
        ("FIX A2: very loose (weak=0.20 be=$2 small=$8)", 0.20, 2.00, 8.00, False, 20),
        ("FIX A3: almost off (weak=0.15 be=$3 small=$10)",0.15, 3.00, 10.0, False, 20),
        ("FIX B: trend filter (current thresholds)",      0.40, 0.50, 3.00, True,  20),
        ("FIX C: trend + relaxed",                         0.25, 1.00, 5.00, True,  20),
        ("FIX D: trend ADX>=15",                           0.40, 0.50, 3.00, True,  15),
        ("FIX E: trend ADX>=25 strict",                    0.40, 0.50, 3.00, True,  25),
    ]
    for label, w, bt, sl, tr, am in cases:
        r = run(df, **params, weak_t=w, be_tol=bt, small_loss=sl, trend_on=tr, adx_min=am)
        if not r: print(f"{label:<40} NO DATA"); continue
        print(f"{label:<40} {r['n']:<5} {r['n']/days:<5.2f} {r['wr']:<6.1f} {r['true_wr']:<6.1f} ${r['aw']:<5.2f} ${r['al']:<5.2f} {r['avg_h']:<5.1f} ${r['net']:+8.2f}")


if __name__ == "__main__":
    main()