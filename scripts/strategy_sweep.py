"""
scripts/strategy_sweep.py
──────────────────────────
Run all 10 strategy presets against each symbol. Identifies the best
strategy per market.

Per market: fetches M15 data ONCE, then runs all 10 strategies on that
shared dataset. Outputs a matrix of NET P/L per (market, strategy).

Usage:
  python scripts/strategy_sweep.py                   # all 15 markets
  python scripts/strategy_sweep.py SYMBOL [SYMBOL2]  # specific markets

Env: BT_START / BT_END (YYYY-MM-DD) override default Jan-Apr window.
"""
import os, sys
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect
from strategies.trend_follower import find_entry, trend_flipped
from strategies.strategy_presets import STRATEGIES
from config.markets import MARKETS


# ── Backtest window ──────────────────────────────────────────────────────
def _parse_date(s, default):
    if not s: return default
    y, m, d = (int(x) for x in s.split("-"))
    return datetime(y, m, d, tzinfo=timezone.utc)
START_DATE = _parse_date(os.environ.get("BT_START"), datetime(2026, 3, 22, tzinfo=timezone.utc))
END_DATE   = _parse_date(os.environ.get("BT_END"),   datetime(2026, 4, 22, tzinfo=timezone.utc))


# ── Per-symbol specs ─────────────────────────────────────────────────────
_forex_m  = {"spread": 0.00010, "slippage": 0.00003, "contract": 100_000}
_jpy_m    = {"spread": 0.010,   "slippage": 0.003,   "contract": 667}
# Exotics: wider spreads. Contract simplified — P/L treated as if quote=USD
# (rough approximation; real account would convert via current rate).
_scandi_m = {"spread": 0.0010,  "slippage": 0.0005,  "contract": 100_000}
_emerging = {"spread": 0.005,   "slippage": 0.003,   "contract": 10_000}    # USDMXN/USDZAR — quoted in foreign ccy, scaled

SYMBOL_SPECS = {
    "EURUSD": _forex_m, "GBPUSD": _forex_m, "AUDUSD": _forex_m, "NZDUSD": _forex_m,
    "USDCAD": _forex_m, "USDCHF": _forex_m, "USDSGD": _forex_m,
    "USDJPY": _jpy_m,   "EURJPY": _jpy_m,   "GBPJPY": _jpy_m,
    "AUDJPY": _jpy_m,   "CADJPY": _jpy_m,   "CHFJPY": _jpy_m, "NZDJPY": _jpy_m,
    "EURGBP": _forex_m, "EURAUD": _forex_m, "AUDNZD": _forex_m,
    "GBPCAD": _forex_m, "GBPCHF": _forex_m, "GBPAUD": _forex_m, "GBPNZD": _forex_m,
    "EURCAD": _forex_m, "EURCHF": _forex_m, "EURNZD": _forex_m,
    "CADCHF": _forex_m, "NZDCAD": _forex_m,
    # Round 3 additions
    "AUDCAD": _forex_m, "AUDCHF": _forex_m, "GBPSGD": _forex_m,
    "USDSEK": _scandi_m, "USDNOK": _scandi_m, "USDPLN": _scandi_m,
    "USDMXN": _emerging, "USDZAR": _emerging,
}


def _spec_for(symbol: str) -> dict:
    base = symbol.rstrip("mc")
    return SYMBOL_SPECS.get(base, {"spread": 1.0, "slippage": 0.5, "contract": 100_000})


@dataclass
class BTTrade:
    direction:   str
    pattern:     str
    entry_time:  pd.Timestamp
    entry_price: float
    sl:          float
    tp:          float
    lot:         float
    exit_time:   Optional[pd.Timestamp] = None
    exit_price:  Optional[float] = None
    exit_reason: Optional[str]   = None
    pnl_usd:     Optional[float] = None


def fetch_range(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M15, start, end)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={"open":"Open","high":"High","low":"Low",
                       "close":"Close","tick_volume":"Volume"}, inplace=True)
    return df


def simulate(df: pd.DataFrame, entry_cfg: dict, spread: float, slippage: float,
             contract: float, lot: float = 0.01) -> List[BTTrade]:
    """Run trade simulation on pre-fetched dataframe with given entry config.
    Single trade A only (no Trade B). Returns closed trades."""
    if df.empty:
        return []
    closed: List[BTTrade] = []
    open_t: Optional[BTTrade] = None
    last_exit_idx = -10**9
    cooldown_bars = entry_cfg.get("cooldown_bars", 0)
    ema_trend_period = entry_cfg.get("ema_trend", 200)
    chop_band = entry_cfg.get("chop_band_atr", 0.5)

    start_i = max(210, ema_trend_period + 10)
    total_bars = len(df) - 1

    for i in range(start_i, total_bars):
        next_bar = df.iloc[i+1]
        nb_high  = float(next_bar["High"])
        nb_low   = float(next_bar["Low"])

        if open_t is not None:
            tr = open_t
            exit_price  = None
            exit_reason = None

            if tr.direction == "BUY" and nb_low <= tr.sl:
                exit_price = tr.sl - slippage; exit_reason = "SL"
            elif tr.direction == "SELL" and nb_high >= tr.sl:
                exit_price = tr.sl + slippage; exit_reason = "SL"

            if exit_reason is None:
                if tr.direction == "BUY" and nb_high >= tr.tp:
                    exit_price = tr.tp - spread; exit_reason = "TP"
                elif tr.direction == "SELL" and nb_low <= tr.tp:
                    exit_price = tr.tp + spread; exit_reason = "TP"

            if exit_reason is None:
                if trend_flipped(df.iloc[:i+1], tr.direction,
                                 ema_trend_period=ema_trend_period,
                                 bar_idx=-1, chop_band_atr=chop_band):
                    exit_price = float(next_bar["Open"]) - spread if tr.direction == "BUY" \
                                 else float(next_bar["Open"]) + spread
                    exit_reason = "trend_flip"

            if exit_reason:
                tr.exit_time   = next_bar["time"]
                tr.exit_price  = exit_price
                tr.exit_reason = exit_reason
                pm = (exit_price - tr.entry_price) if tr.direction == "BUY" \
                     else (tr.entry_price - exit_price)
                tr.pnl_usd = round(pm * lot * contract, 4)
                closed.append(tr)
                open_t = None
                last_exit_idx = i

        if open_t is not None:
            continue
        if i - last_exit_idx <= cooldown_bars:
            continue

        slice_to_now = df.iloc[:i+1]
        setup = find_entry(slice_to_now, entry_cfg, bar_idx=-1)
        if setup is None:
            continue

        max_sl_usd = entry_cfg.get("max_sl_usd", 0)
        if max_sl_usd > 0:
            sl_dist = abs(setup.entry_price - setup.sl)
            if sl_dist * lot * contract > max_sl_usd:
                continue

        entry_px = float(next_bar["Open"])
        ews = entry_px + spread if setup.direction == "BUY" else entry_px - spread
        open_t = BTTrade(
            direction=setup.direction, pattern=setup.pattern,
            entry_time=next_bar["time"], entry_price=ews,
            sl=setup.sl, tp=setup.tp, lot=lot,
        )

    # Force-close any still-open at period end
    if open_t is not None:
        tr = open_t
        final_close = float(df["Close"].iloc[-1])
        exit_px = final_close - spread if tr.direction == "BUY" else final_close + spread
        tr.exit_time   = df["time"].iloc[-1]
        tr.exit_price  = exit_px
        tr.exit_reason = "period_end"
        pm = (exit_px - tr.entry_price) if tr.direction == "BUY" \
             else (tr.entry_price - exit_px)
        tr.pnl_usd = round(pm * lot * contract, 4)
        closed.append(tr)

    return closed


def stats(trades: List[BTTrade]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0.0, "net": 0.0, "avg_w": 0.0, "avg_l": 0.0}
    n = len(trades)
    wins = [t for t in trades if (t.pnl_usd or 0) > 0]
    losses = [t for t in trades if (t.pnl_usd or 0) < 0]
    return {
        "n":     n,
        "wr":    100 * len(wins) / n,
        "net":   sum(t.pnl_usd for t in trades),
        "avg_w": sum(t.pnl_usd for t in wins) / len(wins) if wins else 0.0,
        "avg_l": sum(t.pnl_usd for t in losses) / len(losses) if losses else 0.0,
    }


def resolve_symbol(market_key: str, candidates: List[str]) -> Optional[str]:
    """Resolve broker symbol; reconnect once if MT5 dropped (long sweeps can
    let the connection go stale)."""
    for cand in candidates:
        info = mt5.symbol_info(cand)
        if info is not None:
            return cand
    # First pass returned None for all candidates — try a fresh MT5 reconnect.
    disconnect()
    if not connect():
        return None
    for cand in candidates:
        if mt5.symbol_info(cand):
            return cand
    return None


def main():
    syms_arg = sys.argv[1:]
    if syms_arg:
        targets = syms_arg
    else:
        targets = list(MARKETS.keys())

    if not connect():
        print("MT5 connect failed"); return

    # Result matrix: market → strategy → stats
    results: Dict[str, Dict[str, dict]] = {}

    for market in targets:
        cfg = MARKETS.get(market)
        if cfg is None:
            print(f"[skip] {market}: not in MARKETS"); continue
        symbol = resolve_symbol(market, cfg["symbol_candidates"])
        if symbol is None:
            print(f"[skip] {market}: no symbol on broker"); continue
        spec = _spec_for(symbol)

        print(f"\n── {market} ({symbol}) ──")
        print(f"  Fetching M15 {START_DATE.date()} → {END_DATE.date()}...", end=" ", flush=True)
        df = fetch_range(symbol, START_DATE, END_DATE)
        print(f"{len(df)} bars")
        if df.empty:
            continue

        results[market] = {}
        for strat_name, strat_cfg in STRATEGIES.items():
            trades = simulate(df, strat_cfg, spec["spread"], spec["slippage"],
                              spec["contract"])
            s = stats(trades)
            results[market][strat_name] = s
            print(f"  {strat_name:<14} {s['n']:>4} trades | WR {s['wr']:>5.1f}% | NET ${s['net']:>+8.2f}")

    disconnect()

    # ── Matrix summary ───────────────────────────────────────────────
    if not results:
        return
    print("\n" + "="*120)
    print("STRATEGY × MARKET MATRIX  (NET P/L per market per strategy, 30-day backtest)")
    print("="*120)
    strat_names = list(STRATEGIES.keys())
    header = f"  {'market':<10}" + "".join(f"{s[:10]:>11}" for s in strat_names) + f"{'BEST':>14}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for market, by_strat in results.items():
        row_cells = []
        best_strat, best_net = None, -1e18
        for sn in strat_names:
            net = by_strat.get(sn, {}).get("net", 0.0)
            row_cells.append(f"{net:>+11.2f}")
            if net > best_net:
                best_net, best_strat = net, sn
        verdict = "++" if best_net > 5 else ("+" if best_net > 0 else "-")
        print(f"  {market:<10}" + "".join(row_cells) + f"  {best_strat:>10}{verdict:<3}")

    # ── Per-market best strategy (WR ≥ 45% AND NET > 0) ─────────────
    WR_FLOOR = 45.0
    print("\n" + "="*120)
    print(f"BEST STRATEGY PER MARKET — admission gate: WR >= {WR_FLOOR}% AND NET > 0")
    print("="*120)
    print(f"  {'market':<10}  {'best strategy':<14}  {'trades':>7}  {'WR':>6}  {'NET':>10}  verdict")
    print(f"  {'-'*10}  {'-'*14}  {'-'*7}  {'-'*6}  {'-'*10}  {'-'*10}")
    qualified = []
    for market, by_strat in results.items():
        # Filter to qualifying strategies (WR >= floor AND NET > 0)
        passing = [(sn, s) for sn, s in by_strat.items()
                   if s["wr"] >= WR_FLOOR and s["net"] > 0]
        if passing:
            sn, s = max(passing, key=lambda kv: kv[1]["net"])
            verdict = "ADMIT"
            qualified.append((market, sn, s["net"], s["wr"]))
        else:
            # Show the highest-NET as info even though it doesn't qualify
            sn, s = max(by_strat.items(), key=lambda kv: kv[1]["net"])
            verdict = "REJECT"
        print(f"  {market:<10}  {sn:<14}  {s['n']:>7}  {s['wr']:>5.1f}%  ${s['net']:>+9.2f}  {verdict}")

    print(f"\n  {len(qualified)} of {len(results)} markets pass the admission gate.")
    if qualified:
        print("\n  Qualified markets (lock these):")
        for market, sn, net, wr in sorted(qualified, key=lambda x: -x[2]):
            print(f"    {market:<10}  preset={sn:<14}  WR={wr:.1f}%  NET=${net:+.2f}")


if __name__ == "__main__":
    main()