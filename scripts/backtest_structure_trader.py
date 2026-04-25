"""
scripts/backtest_structure_trader.py
─────────────────────────────────────
Phase 7: Honest backtest of the structure trader.

Design principles (addressing what went wrong before):
  - Strictly causal: at each M15 bar i, we only look at df.iloc[:i+1].
  - Level memory rebuilt bar-by-bar (no look-ahead).
  - Spread applied on entry AND exit.
  - Slippage applied on SL hits.
  - Dual trades (A + B) simulated independently.
  - Active M15 structure monitor replayed.
  - Structural cooldown enforced.
  - If SL and TP both touched in the same bar, assume SL hits first (conservative).

Period: 2026-02-01 to 2026-04-21 (Feb + Mar + Apr).
Symbol: XAUUSD (Exness Raw spreads).
"""
import os, sys, sqlite3, math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect
from strategies.market_structure import find_swing_points
from strategies.mtf_analysis import analyze_mtf, BIAS_BUY, BIAS_SELL, BIAS_RANGE, BIAS_NEUTRAL
from strategies.level_memory import LevelMemory
from strategies.entry_engine import find_entry, _atr
from strategies.structure_trader import latest_confirmed_swing_time, cooldown_cleared
from config.markets import MARKETS


# ── Backtest config ────────────────────────────────────────────────────────
START_DATE    = datetime(2026, 1, 1,  tzinfo=timezone.utc)
END_DATE      = datetime(2026, 4, 22, tzinfo=timezone.utc)
# Pick symbol from CLI arg if provided, else first market in config.
SYMBOL        = sys.argv[1] if len(sys.argv) > 1 else next(iter(MARKETS.keys()))
BACKTEST_DB   = os.path.join("data", f"backtest_levels_{SYMBOL}.db")

# Per-symbol spreads/slippage + contract size. Spreads measured on Exness
# Real Micro (suffix 'm'). For JPY pairs, "contract" is the effective USD per
# 1.0 lot per 1.0 price unit (100_000 / USDJPY_rate ≈ 667 at rate 150) — this
# makes P/L come out in USD without needing a live FX conversion inside the loop.
_forex_m = {"spread": 0.00010, "slippage": 0.00003, "contract": 100_000}
_jpy_m   = {"spread": 0.010,   "slippage": 0.003,   "contract": 667}
SYMBOL_SPECS = {
    "XAUUSD": {"spread": 0.28,    "slippage": 0.15,    "contract": 100},
    "XAUUSDm":{"spread": 0.28,    "slippage": 0.15,    "contract": 100},
    "BTCUSD": {"spread": 6.00,    "slippage": 3.00,    "contract": 1.0},
    "BTCUSDm":{"spread": 6.00,    "slippage": 3.00,    "contract": 1.0},
    "EURUSD": {"spread": 0.00008, "slippage": 0.00002, "contract": 100_000},
    "EURUSDm":{"spread": 0.00008, "slippage": 0.00002, "contract": 100_000},
    "GBPUSD": _forex_m, "GBPUSDm": _forex_m,
    "USDJPY": _jpy_m,   "USDJPYm": _jpy_m,
    "AUDUSD": {"spread": 0.00009, "slippage": 0.00003, "contract": 100_000},
    "AUDUSDm":{"spread": 0.00009, "slippage": 0.00003, "contract": 100_000},
}
_spec = SYMBOL_SPECS.get(SYMBOL, {"spread": 1.0, "slippage": 0.5, "contract": 1.0})
SPREAD        = _spec["spread"]
SLIPPAGE      = _spec["slippage"]
CONTRACT_SIZE = _spec["contract"]


# ── Fetch helpers ──────────────────────────────────────────────────────────

def fetch_range(symbol: str, tf: int, start: datetime, end: datetime) -> pd.DataFrame:
    rates = mt5.copy_rates_range(symbol, tf, start, end)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "tick_volume": "Volume",
    }, inplace=True)
    return df


# ── Data structures ────────────────────────────────────────────────────────

@dataclass
class BTTrade:
    role:        str            # "A" or "B"
    direction:   str            # "BUY" or "SELL"
    scenario:    str            # entry scenario
    entry_time:  pd.Timestamp
    entry_price: float          # includes spread
    sl:          float
    tp:          float          # Trade B: target price; Trade A: structural TP
    lot:         float
    invalidation: float         # structural break level (A only; still tracked for B)
    target_price: Optional[float] = None   # Trade B: price where +$2 hits
    exit_time:   Optional[pd.Timestamp] = None
    exit_price:  Optional[float] = None
    exit_reason: Optional[str]   = None
    pnl_usd:     Optional[float] = None     # account-currency P/L after spread + slippage
    pnl_R:       Optional[float] = None     # P/L in R units (|entry-sl|)


# ── P/L math ───────────────────────────────────────────────────────────────

def price_pnl(tr: BTTrade, exit_price: float) -> float:
    return (exit_price - tr.entry_price) if tr.direction == "BUY" else (tr.entry_price - exit_price)


def to_usd(price_move: float, lot: float) -> float:
    return price_move * lot * CONTRACT_SIZE


# ── Backtest main loop ─────────────────────────────────────────────────────

def clear_backtest_db():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(BACKTEST_DB):
        os.remove(BACKTEST_DB)


def run_backtest(cfg: dict) -> List[BTTrade]:
    # Fetch all data upfront; we'll slice it causally inside the loop
    print(f"Fetching data {START_DATE.date()} → {END_DATE.date()}...")
    df_h4  = fetch_range(SYMBOL, mt5.TIMEFRAME_H4,  START_DATE, END_DATE)
    df_h1  = fetch_range(SYMBOL, mt5.TIMEFRAME_H1,  START_DATE, END_DATE)
    df_m15 = fetch_range(SYMBOL, mt5.TIMEFRAME_M15, START_DATE, END_DATE)
    print(f"  H4:  {len(df_h4):>5} bars")
    print(f"  H1:  {len(df_h1):>5} bars")
    print(f"  M15: {len(df_m15):>5} bars")

    if df_m15.empty:
        print("No M15 data — aborting")
        return []

    clear_backtest_db()
    mem = LevelMemory(db_path=BACKTEST_DB)

    struct_cfg = cfg["structure"]
    entry_cfg  = cfg["entry"]
    dual       = cfg["dual_trade"]
    lot_a      = dual["trade_a_lot"]
    lot_b      = dual["trade_b_lot"]
    tp_b_usd   = dual["trade_b_profit_usd"]

    closed_trades: List[BTTrade] = []
    open_trades:   List[BTTrade] = []
    last_exit_time_iso: Optional[str] = None

    # Warmup: need 210+ M15 bars for EMA200 derived structures
    start_i = 210
    total_bars = len(df_m15) - 1
    print(f"\nReplaying bars {start_i}..{total_bars} ({total_bars - start_i} iterations)")

    progress_step = max(1, (total_bars - start_i) // 20)

    for i in range(start_i, total_bars):
        if (i - start_i) % progress_step == 0:
            pct = 100 * (i - start_i) / (total_bars - start_i)
            print(f"  {pct:>5.1f}% | bar {i}/{total_bars} | open {len(open_trades)} | closed {len(closed_trades)}")

        m15_slice = df_m15.iloc[:i+1]
        bar_time  = m15_slice["time"].iloc[-1]
        h4_slice  = df_h4[df_h4["time"] <= bar_time]
        h1_slice  = df_h1[df_h1["time"] <= bar_time]
        if len(h4_slice) < 100 or len(h1_slice) < 100:
            continue

        # ── Manage open trades against the NEXT bar ─────
        next_bar = df_m15.iloc[i+1]
        nb_high = float(next_bar["High"])
        nb_low  = float(next_bar["Low"])
        current_close = float(m15_slice["Close"].iloc[-1])   # last CLOSED bar close

        for tr in list(open_trades):
            exit_price = None
            exit_reason = None

            # Priority 1: hard SL (worst case — always checked first)
            if tr.direction == "BUY" and nb_low <= tr.sl:
                exit_price = tr.sl - SLIPPAGE
                exit_reason = "SL"
            elif tr.direction == "SELL" and nb_high >= tr.sl:
                exit_price = tr.sl + SLIPPAGE
                exit_reason = "SL"

            # Priority 2: TP (broker-side). For A it's structural; for B it's the $ target price.
            if exit_reason is None:
                if tr.role == "B" and tr.target_price is not None:
                    tp_px = tr.target_price
                    if tr.direction == "BUY" and nb_high >= tp_px:
                        exit_price = tp_px - SPREAD
                        exit_reason = "B_target"
                    elif tr.direction == "SELL" and nb_low <= tp_px:
                        exit_price = tp_px + SPREAD
                        exit_reason = "B_target"
                elif tr.role == "A":
                    if tr.direction == "BUY" and nb_high >= tr.tp:
                        exit_price = tr.tp - SPREAD
                        exit_reason = "TP"
                    elif tr.direction == "SELL" and nb_low <= tr.tp:
                        exit_price = tr.tp + SPREAD
                        exit_reason = "TP"

            # Priority 3 (A only): M15 structure invalidation
            # Triggers when current bar closed beyond the invalidation level.
            if exit_reason is None and tr.role == "A":
                broke = (tr.direction == "BUY"  and current_close < tr.invalidation) or \
                        (tr.direction == "SELL" and current_close > tr.invalidation)
                if broke:
                    # Close at next bar open (simulate market close one bar after signal)
                    exit_price = float(next_bar["Open"]) - SPREAD if tr.direction == "BUY" \
                                 else float(next_bar["Open"]) + SPREAD
                    exit_reason = "structure_broken"

            if exit_reason:
                tr.exit_time   = next_bar["time"]
                tr.exit_price  = exit_price
                tr.exit_reason = exit_reason
                pm = price_pnl(tr, exit_price)
                tr.pnl_usd = round(to_usd(pm, tr.lot), 4)
                sl_dist = abs(tr.entry_price - tr.sl)
                tr.pnl_R = round(pm / sl_dist, 3) if sl_dist > 0 else 0
                closed_trades.append(tr)
                open_trades.remove(tr)
                last_exit_time_iso = tr.exit_time.isoformat()

                # ★ When struct_B hits target, move struct_A's SL to BE + $0.10 buffer.
                if tr.role == "B" and exit_reason == "B_target":
                    be_buffer = 0.10
                    new_sl = tr.entry_price + be_buffer if tr.direction == "BUY" else tr.entry_price - be_buffer
                    for open_a in open_trades:
                        if open_a.role == "A" and open_a.direction == tr.direction:
                            open_a.sl = new_sl
                            break

        # ── Update level memory AFTER trade management, BEFORE new entry check ──
        mem.update(SYMBOL, "H4",  h4_slice,  swing_left=struct_cfg["swing_left"], swing_right=struct_cfg["swing_right"], range_band_pct=struct_cfg["h4_range_band_pct"])
        mem.update(SYMBOL, "H1",  h1_slice,  swing_left=struct_cfg["swing_left"], swing_right=struct_cfg["swing_right"], range_band_pct=struct_cfg["h1_range_band_pct"])
        mem.update(SYMBOL, "M15", m15_slice, swing_left=struct_cfg["swing_left"], swing_right=struct_cfg["swing_right"], range_band_pct=struct_cfg["m15_range_band_pct"])

        # Only look for new entries if NO open trades
        if open_trades:
            continue

        mtf = analyze_mtf(
            h4_slice, h1_slice, m15_slice,
            left=struct_cfg["swing_left"], right=struct_cfg["swing_right"],
            min_swings=struct_cfg["min_swings"],
            range_band_pct=struct_cfg["m15_range_band_pct"],
            h4_range_band=struct_cfg["h4_range_band_pct"],
        )
        if mtf.bias == BIAS_NEUTRAL:
            continue

        setup = find_entry(mtf, mem, m15_slice, SYMBOL, cfg=entry_cfg)
        if setup is None:
            continue

        # SL floor
        min_sl_atr = entry_cfg.get("min_sl_atr", 0)
        if min_sl_atr > 0:
            atr = _atr(m15_slice)
            if abs(setup.entry_price - setup.sl) < min_sl_atr * atr:
                continue

        # SL cap — reject setups where Trade A's $ loss would exceed max
        max_sl_usd = entry_cfg.get("max_sl_usd", 0)
        if max_sl_usd > 0:
            sl_dist = abs(setup.entry_price - setup.sl)
            a_loss = sl_dist * lot_a * CONTRACT_SIZE
            if a_loss > max_sl_usd:
                continue

        # Cooldown
        latest_sw = latest_confirmed_swing_time(
            m15_slice, left=struct_cfg["swing_left"], right=struct_cfg["swing_right"],
        )
        if not cooldown_cleared(last_exit_time_iso, latest_sw):
            continue

        # ── Enter Trade A + Trade B at next bar OPEN ──
        entry_px = float(next_bar["Open"])
        entry_with_spread = entry_px + SPREAD if setup.direction == "BUY" else entry_px - SPREAD

        a = BTTrade(
            role="A", direction=setup.direction, scenario=setup.scenario,
            entry_time=next_bar["time"], entry_price=entry_with_spread,
            sl=setup.sl, tp=setup.tp_a, lot=lot_a,
            invalidation=setup.invalidation_price,
        )
        open_trades.append(a)

        if tp_b_usd > 0 and lot_b > 0:
            # Trade B's TP price
            price_move_for_b = tp_b_usd / (lot_b * CONTRACT_SIZE)
            b_target = (entry_with_spread + price_move_for_b) if setup.direction == "BUY" \
                       else (entry_with_spread - price_move_for_b)

            # Trade B's TIGHTER SL — capped by max-loss-$
            b_max_loss = cfg["dual_trade"].get("trade_b_max_loss_usd", 5.0)
            struct_sl_dist = abs(entry_with_spread - setup.sl)
            b_max_dist = b_max_loss / (lot_b * CONTRACT_SIZE) if b_max_loss > 0 else struct_sl_dist
            b_sl_dist = min(struct_sl_dist, b_max_dist)
            b_sl = (entry_with_spread - b_sl_dist) if setup.direction == "BUY" \
                   else (entry_with_spread + b_sl_dist)

            b = BTTrade(
                role="B", direction=setup.direction, scenario=setup.scenario,
                entry_time=next_bar["time"], entry_price=entry_with_spread,
                sl=b_sl, tp=b_target, lot=lot_b,
                invalidation=setup.invalidation_price, target_price=b_target,
            )
            open_trades.append(b)

    # Close any still-open at end of period
    for tr in open_trades:
        final_close = float(df_m15["Close"].iloc[-1])
        exit_px = final_close - SPREAD if tr.direction == "BUY" else final_close + SPREAD
        tr.exit_time   = df_m15["time"].iloc[-1]
        tr.exit_price  = exit_px
        tr.exit_reason = "period_end"
        pm = price_pnl(tr, exit_px)
        tr.pnl_usd = round(to_usd(pm, tr.lot), 4)
        sl_dist = abs(tr.entry_price - tr.sl)
        tr.pnl_R = round(pm / sl_dist, 3) if sl_dist > 0 else 0
        closed_trades.append(tr)

    return closed_trades


# ── Reporting ──────────────────────────────────────────────────────────────

def summarize(trades: List[BTTrade]):
    if not trades:
        print("\nNO TRADES generated during backtest period.")
        return

    print("\n" + "="*100)
    print(f"BACKTEST RESULTS — {len(trades)} trades from {trades[0].entry_time.date()} to {trades[-1].exit_time.date()}")
    print("="*100)

    # Per-role stats
    for role in ("A", "B"):
        subset = [t for t in trades if t.role == role]
        if not subset: continue
        wins = [t for t in subset if (t.pnl_usd or 0) > 0]
        losses = [t for t in subset if (t.pnl_usd or 0) < 0]
        wr = len(wins)/len(subset)*100 if subset else 0
        net = sum(t.pnl_usd for t in subset)
        avg_w = sum(t.pnl_usd for t in wins)/len(wins) if wins else 0
        avg_l = sum(t.pnl_usd for t in losses)/len(losses) if losses else 0
        print(f"\n  Role {role}:  {len(subset)} trades | WR {wr:.1f}% ({len(wins)}W/{len(losses)}L) | "
              f"Avg W ${avg_w:+.2f} | Avg L ${avg_l:+.2f} | NET ${net:+.2f}")

    # Exit reason breakdown
    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, {"n": 0, "pnl": 0})
        reasons[t.exit_reason]["n"] += 1
        reasons[t.exit_reason]["pnl"] += t.pnl_usd or 0
    print("\n  By exit reason:")
    for reason, s in sorted(reasons.items(), key=lambda kv: -kv[1]["pnl"]):
        print(f"    {reason:<22} {s['n']:>3} trades  | total ${s['pnl']:+.2f}")

    # Per-scenario
    scenarios = {}
    for t in trades:
        if t.role != "A": continue     # A is the primary setup, B piggy-backs
        scenarios[t.scenario] = scenarios.get(t.scenario, {"n": 0, "wins": 0, "pnl": 0})
        scenarios[t.scenario]["n"] += 1
        if (t.pnl_usd or 0) > 0: scenarios[t.scenario]["wins"] += 1
        scenarios[t.scenario]["pnl"] += t.pnl_usd or 0
    print("\n  By scenario (Trade A only):")
    for scen, s in scenarios.items():
        wr = s["wins"]/s["n"]*100 if s["n"] else 0
        print(f"    {scen:<22} {s['n']:>3} trades  | WR {wr:.1f}% | NET ${s['pnl']:+.2f}")

    # Monthly breakdown
    print("\n  By month:")
    months = {}
    for t in trades:
        key = f"{t.entry_time.year}-{t.entry_time.month:02d}"
        months[key] = months.get(key, {"n": 0, "pnl": 0, "wins": 0})
        months[key]["n"] += 1
        months[key]["pnl"] += t.pnl_usd or 0
        if (t.pnl_usd or 0) > 0: months[key]["wins"] += 1
    for key in sorted(months.keys()):
        s = months[key]
        wr = s["wins"]/s["n"]*100 if s["n"] else 0
        print(f"    {key}  {s['n']:>3} trades  | WR {wr:.1f}% | NET ${s['pnl']:+.2f}")

    # Drawdown + equity
    equity = 0
    peak = 0
    max_dd = 0
    for t in sorted(trades, key=lambda x: x.exit_time):
        equity += t.pnl_usd or 0
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    total_net = sum(t.pnl_usd or 0 for t in trades)
    print("\n" + "-"*100)
    print(f"  TOTAL NET P/L:     ${total_net:+.2f}")
    print(f"  Max drawdown:      ${max_dd:+.2f}")
    print(f"  Trades per week:   {len(trades) / max(1, (trades[-1].exit_time - trades[0].entry_time).days / 7):.2f}")

    # Dump individual trades (first 30)
    print("\n  First 30 trades (chronological):")
    for t in sorted(trades, key=lambda x: x.entry_time)[:30]:
        print(f"    {str(t.entry_time)[:19]}  {t.role}  {t.direction:<4}  {t.scenario:<18}  "
              f"entry ${t.entry_price:>9.2f}  sl ${t.sl:>9.2f}  tp ${t.tp:>9.2f}  "
              f"exit ${t.exit_price:>9.2f} ({t.exit_reason:<22})  P/L ${t.pnl_usd:+.2f}")


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    if not connect(): return
    mt5.symbol_select(SYMBOL, True)
    # Resolve config: direct key, or scan symbol_candidates for a match.
    cfg = MARKETS.get(SYMBOL)
    if cfg is None:
        for k, v in MARKETS.items():
            if SYMBOL in v.get("symbol_candidates", []):
                cfg = v
                break
    if cfg is None:
        print(f"No config found for {SYMBOL}")
        disconnect(); return
    print(f"\nConfig: strategy={cfg['strategy']}  lot_A={cfg['dual_trade']['trade_a_lot']}  lot_B={cfg['dual_trade']['trade_b_lot']}  tp_B=${cfg['dual_trade']['trade_b_profit_usd']}")
    print(f"Spread modeled: ${SPREAD}  |  Slippage: ${SLIPPAGE}")

    trades = run_backtest(cfg)
    summarize(trades)

    disconnect()


if __name__ == "__main__":
    main()