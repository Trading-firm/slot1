"""
scripts/backtest_sweep.py
──────────────────────────
Parameter sweep backtester. For each market, tests combinations of:
  - ADX threshold
  - RSI band width
  - HTF (H1) trend filter on/off
  - Pullback tolerance (strict vs loose)
  - Session window (current / extended / 24-7)

Scores each combo on: trades, trades/day, win rate, net R, expectancy.
Picks the best config per market by expectancy with a trades/day floor.

Usage:
    python scripts/backtest_sweep.py
"""
import os, sys, json, math, itertools
from datetime import timedelta
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())

from config.markets import MARKETS
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.indicators import calc_ema, calc_rsi, calc_atr, calc_adx, calc_swing_points

DAYS       = 90
MIN_TRADES_PER_DAY = 0.3   # drop configs that signal less than this
BARS_PER_DAY = {"M5": 288, "M15": 96, "M30": 48, "H1": 24}

# ── Parameter grid ─────────────────────────────────────────────────────────
ADX_VALUES      = [18, 22, 25]
RSI_BANDS       = {
    "narrow": {"buy": (35, 58), "sell": (42, 65)},
    "wide":   {"buy": (30, 65), "sell": (35, 70)},
}
HTF_VALUES      = [True, False]
PULLBACK_TOL    = {"strict": 0.0, "loose": 0.3}   # fraction of ATR
SESSION_MODES   = ["current", "extended", "247"]

EXTENDED_WAT    = [{"start": 6, "end": 23}]   # near-24h with wind-down


def precompute(df: pd.DataFrame):
    return {
        "ema20":  calc_ema(df, 20).values,
        "ema50":  calc_ema(df, 50).values,
        "ema200": calc_ema(df, 200).values,
        "atr":    calc_atr(df, 14).values,
        "rsi":    calc_rsi(df, 14).values,
        "adx":    calc_adx(df, 14).values,
        "open":   df["Open"].values,
        "high":   df["High"].values,
        "low":    df["Low"].values,
        "close":  df["Close"].values,
        "time":   df["time"].values if "time" in df.columns else None,
    }


def precompute_htf_trend(htf_df: pd.DataFrame):
    """Returns (htf_ema50, htf_ema200, htf_times) for alignment by time."""
    if htf_df is None or htf_df.empty:
        return None
    return {
        "ema50":  calc_ema(htf_df, 50).values,
        "ema200": calc_ema(htf_df, 200).values,
        "time":   htf_df["time"].values,
    }


def htf_aligned_uptrend(htf, bar_time):
    """Return (uptrend, downtrend) booleans for HTF at or before bar_time."""
    if htf is None:
        return True, True   # no HTF data → allow both
    idx = htf["time"].searchsorted(bar_time, side="right") - 1
    if idx < 200:
        return True, True
    e50, e200 = htf["ema50"][idx], htf["ema200"][idx]
    if math.isnan(e50) or math.isnan(e200):
        return True, True
    return e50 > e200, e50 < e200


def in_session(bar_time, sessions):
    if not sessions:
        return True
    # bar_time is np.datetime64 — convert to pd.Timestamp for .hour
    ts = pd.Timestamp(bar_time) + pd.Timedelta(hours=1)   # broker→WAT approx
    h  = ts.hour
    for s in sessions:
        if s["start"] <= h <= s["end"]:
            return True
    return False


def run_backtest(ind, htf, cfg_params, swing_highs, swing_lows, max_sl_atr=2.5, swing_window=10):
    """
    ind: precomputed indicator arrays
    htf: precomputed HTF trend (or None)
    cfg_params: dict with keys adx_min, rsi_buy, rsi_sell, htf_on, pullback_tol, sessions
    Returns dict with trade stats.
    """
    n = len(ind["close"])
    adx_min      = cfg_params["adx_min"]
    rsi_buy_lo, rsi_buy_hi   = cfg_params["rsi_buy"]
    rsi_sell_lo, rsi_sell_hi = cfg_params["rsi_sell"]
    htf_on       = cfg_params["htf_on"]
    pull_tol     = cfg_params["pullback_tol"]
    sessions     = cfg_params["sessions"]

    trades = []
    active = None

    for i in range(250, n - 1):
        c, o, h, l = ind["close"][i], ind["open"][i], ind["high"][i], ind["low"][i]
        e20, e50, e200 = ind["ema20"][i], ind["ema50"][i], ind["ema200"][i]
        atr, rsi, adx = ind["atr"][i], ind["rsi"][i], ind["adx"][i]

        if any(math.isnan(v) for v in (atr, rsi, adx, e20, e50, e200)):
            pass
        elif active is None:
            # Session filter
            t = ind["time"][i] if ind["time"] is not None else None
            if sessions and t is not None and not in_session(t, sessions):
                pass
            elif adx <= adx_min:
                pass
            else:
                tol = atr * pull_tol
                uptrend   = e50 > e200 and c > e200
                downtrend = e50 < e200 and c < e200
                bull = c > o
                bear = c < o
                base_dir = None
                if uptrend and (l <= e20 + tol) and c > e20 and bull and rsi_buy_lo <= rsi <= rsi_buy_hi:
                    base_dir = "BUY"
                elif downtrend and (h >= e20 - tol) and c < e20 and bear and rsi_sell_lo <= rsi <= rsi_sell_hi:
                    base_dir = "SELL"

                if base_dir:
                    # HTF filter
                    if htf_on and t is not None:
                        up, dn = htf_aligned_uptrend(htf, t)
                        if base_dir == "BUY" and not up: base_dir = None
                        if base_dir == "SELL" and not dn: base_dir = None

                if base_dir:
                    # SL/TP structural
                    lo_i = max(0, i - swing_window)
                    recent_low  = swing_lows[lo_i:i].min()  if i > lo_i else l
                    recent_high = swing_highs[lo_i:i].max() if i > lo_i else h
                    if base_dir == "BUY":
                        sl = recent_low - atr * 0.2
                        sl_dist = c - sl
                        if sl_dist > atr * max_sl_atr or sl_dist <= 0:
                            pass
                        else:
                            active = {"dir":"BUY","sl":sl,"tp":c+sl_dist,"entry":c,"bar":i}
                    else:
                        sl = recent_high + atr * 0.2
                        sl_dist = sl - c
                        if sl_dist > atr * max_sl_atr or sl_dist <= 0:
                            pass
                        else:
                            active = {"dir":"SELL","sl":sl,"tp":c-sl_dist,"entry":c,"bar":i}

        if active is not None:
            # Check next bar for hit
            nh, nl = ind["high"][i+1], ind["low"][i+1]
            hit_sl = hit_tp = False
            if active["dir"] == "BUY":
                if nl <= active["sl"]: hit_sl = True
                elif nh >= active["tp"]: hit_tp = True
            else:
                if nh >= active["sl"]: hit_sl = True
                elif nl <= active["tp"]: hit_tp = True
            if hit_sl or hit_tp:
                trades.append(1.0 if hit_tp else -1.0)
                active = None

    if not trades:
        return {"trades":0, "wins":0, "losses":0, "win_rate":0.0, "net_r":0.0, "expectancy":0.0}
    wins   = sum(1 for t in trades if t > 0)
    losses = len(trades) - wins
    wr     = wins / len(trades)
    net_r  = wins - losses
    # expectancy per trade at 1:1 RR
    exp    = wr - (1 - wr)
    return {
        "trades":    len(trades),
        "wins":      wins,
        "losses":    losses,
        "win_rate":  round(wr * 100, 2),
        "net_r":     round(net_r, 1),
        "expectancy":round(exp, 3),
    }


def build_combos(current_sessions):
    combos = []
    for adx, rsi_key, htf, pull_key, sess_key in itertools.product(
        ADX_VALUES, RSI_BANDS.keys(), HTF_VALUES, PULLBACK_TOL.keys(), SESSION_MODES
    ):
        if sess_key == "current":
            sessions = current_sessions
        elif sess_key == "extended":
            sessions = EXTENDED_WAT
        else:
            sessions = []
        combos.append({
            "adx_min":      adx,
            "rsi_key":      rsi_key,
            "rsi_buy":      RSI_BANDS[rsi_key]["buy"],
            "rsi_sell":     RSI_BANDS[rsi_key]["sell"],
            "htf_on":       htf,
            "pullback_tol": PULLBACK_TOL[pull_key],
            "pullback_key": pull_key,
            "sessions":     sessions,
            "session_key":  sess_key,
        })
    return combos


def main():
    print("="*90)
    print(f"PARAMETER SWEEP — {DAYS} days, {len(ADX_VALUES)*len(RSI_BANDS)*len(HTF_VALUES)*len(PULLBACK_TOL)*len(SESSION_MODES)} configs per market")
    print("="*90)

    if not connect():
        print("MT5 connect failed")
        return

    all_results = {}
    per_market_best = {}

    for symbol, cfg in MARKETS.items():
        tf_name = cfg["tf_name"]
        bpd     = BARS_PER_DAY.get(tf_name, 96)
        count   = bpd * DAYS + 300
        print(f"\n--- {symbol} ({tf_name}) — fetching {count} bars ---")
        df  = fetch_candles(symbol, cfg["timeframe"], count=count)
        if df.empty:
            print(f"  no data, skipping")
            continue
        htf_df = fetch_candles(symbol, mt5.TIMEFRAME_H1, count=DAYS*24 + 300)

        ind = precompute(df)
        htf = precompute_htf_trend(htf_df) if not htf_df.empty else None

        sw_highs, sw_lows = calc_swing_points(df, window=cfg.get("swing_window", 10))
        sw_highs, sw_lows = sw_highs.values, sw_lows.values

        days_in_data = max(1, (df["time"].iloc[-1] - df["time"].iloc[0]).days)

        combos = build_combos(cfg["filters"].get("sessions", []))
        results = []
        for cp in combos:
            r = run_backtest(ind, htf, cp, sw_highs, sw_lows,
                             max_sl_atr=cfg.get("max_sl_atr", 2.5),
                             swing_window=cfg.get("swing_window", 10))
            r["trades_per_day"] = round(r["trades"] / days_in_data, 2)
            r["adx_min"]      = cp["adx_min"]
            r["rsi_key"]      = cp["rsi_key"]
            r["htf_on"]       = cp["htf_on"]
            r["pullback_key"] = cp["pullback_key"]
            r["session_key"]  = cp["session_key"]
            results.append(r)

        # Score: prefer expectancy, require min trades/day
        eligible = [r for r in results if r["trades_per_day"] >= MIN_TRADES_PER_DAY and r["trades"] >= 10]
        if not eligible:
            eligible = sorted(results, key=lambda r: r["trades"], reverse=True)[:5]
        # Rank by (expectancy * sqrt(trades)) to balance edge and sample size
        eligible.sort(key=lambda r: r["expectancy"] * math.sqrt(max(r["trades"],1)), reverse=True)

        print(f"  Top 5 configs (of {len(results)}):")
        print(f"  {'ADX':<4} {'RSI':<7} {'HTF':<4} {'Pull':<7} {'Session':<9} | {'Trades':<7} {'T/Day':<6} {'WR':<7} {'NetR':<6} {'Exp':<6}")
        for r in eligible[:5]:
            print(f"  {r['adx_min']:<4} {r['rsi_key']:<7} {str(r['htf_on']):<4} {r['pullback_key']:<7} {r['session_key']:<9} | {r['trades']:<7} {r['trades_per_day']:<6} {r['win_rate']:<7} {r['net_r']:+6.1f} {r['expectancy']:+6.2f}")

        all_results[symbol] = results
        per_market_best[symbol] = eligible[0] if eligible else None

    disconnect()

    # Final summary
    print("\n" + "="*90)
    print("BEST CONFIG PER MARKET (ranked by expectancy * sqrt(trades))")
    print("="*90)
    print(f"{'Market':<24} {'ADX':<4} {'RSI':<7} {'HTF':<4} {'Pull':<7} {'Session':<9} | {'Trades':<7} {'T/D':<5} {'WR%':<6} {'Exp':<6}")
    print("-"*90)
    for m, r in per_market_best.items():
        if r is None:
            print(f"{m:<24} NO ELIGIBLE CONFIG")
            continue
        print(f"{m:<24} {r['adx_min']:<4} {r['rsi_key']:<7} {str(r['htf_on']):<4} {r['pullback_key']:<7} {r['session_key']:<9} | {r['trades']:<7} {r['trades_per_day']:<5} {r['win_rate']:<6} {r['expectancy']:+6.2f}")

    # Save JSON
    out_path = os.path.join(os.getcwd(), "scripts", "backtest_sweep_results.json")
    with open(out_path, "w") as f:
        json.dump({
            "days": DAYS,
            "best": {m: r for m, r in per_market_best.items()},
            "all":  all_results,
        }, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()