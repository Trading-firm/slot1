"""
scripts/backtest_trend_follower.py
───────────────────────────────────
Honest backtest of the EMA trend-follower + candlestick strategy.

Design principles:
  - Strictly causal: at each M15 bar i we only see df.iloc[:i+1].
  - Spread applied on entry AND exit.
  - Slippage applied on SL hits (worst-case).
  - Dual trades A + B simulated independently.
  - Trend-flip early exit replayed bar-by-bar.
  - SL and TP both touched in the same bar → assume SL hits first (conservative).
  - One signal per market at a time (cooldown = "no new entry while position open").

CLI:  python scripts/backtest_trend_follower.py SYMBOL
Env:  BT_START / BT_END (YYYY-MM-DD) override the default Jan-Apr window.
"""
import os, sys
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect
from strategies.trend_follower import find_entry, trend_flipped
from config.markets import MARKETS


# ── Backtest window ────────────────────────────────────────────────────────
def _parse_date(s, default):
    if not s: return default
    y, m, d = (int(x) for x in s.split("-"))
    return datetime(y, m, d, tzinfo=timezone.utc)
START_DATE = _parse_date(os.environ.get("BT_START"), datetime(2026, 1, 1,  tzinfo=timezone.utc))
END_DATE   = _parse_date(os.environ.get("BT_END"),   datetime(2026, 4, 22, tzinfo=timezone.utc))

# Symbol from CLI (or first market).
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else next(iter(MARKETS.keys()))


# ── Per-symbol specs (spread/slippage/contract) ────────────────────────────
_forex_m = {"spread": 0.00010, "slippage": 0.00003, "contract": 100_000}
_jpy_m   = {"spread": 0.010,   "slippage": 0.003,   "contract": 667}
SYMBOL_SPECS = {
    # USD majors
    "EURUSD": _forex_m, "EURUSDm": _forex_m,
    "GBPUSD": _forex_m, "GBPUSDm": _forex_m,
    "AUDUSD": _forex_m, "AUDUSDm": _forex_m,
    "NZDUSD": _forex_m, "NZDUSDm": _forex_m,
    "USDCAD": _forex_m, "USDCADm": _forex_m,
    "USDCHF": _forex_m, "USDCHFm": _forex_m,
    # JPY-quoted
    "USDJPY": _jpy_m,   "USDJPYm": _jpy_m,
    "EURJPY": _jpy_m,   "EURJPYm": _jpy_m,
    "GBPJPY": _jpy_m,   "GBPJPYm": _jpy_m,
    "AUDJPY": _jpy_m,   "AUDJPYm": _jpy_m,
    "CADJPY": _jpy_m,   "CADJPYm": _jpy_m,
    "CHFJPY": _jpy_m,   "CHFJPYm": _jpy_m,
    # Cross pairs (4-decimal, like majors)
    "EURGBP": _forex_m, "EURGBPm": _forex_m,
    "EURAUD": _forex_m, "EURAUDm": _forex_m,
    "AUDNZD": _forex_m, "AUDNZDm": _forex_m,
    # Round 2 candidates
    "GBPCAD": _forex_m, "GBPCADm": _forex_m,
    "GBPCHF": _forex_m, "GBPCHFm": _forex_m,
    "GBPAUD": _forex_m, "GBPAUDm": _forex_m,
    "GBPNZD": _forex_m, "GBPNZDm": _forex_m,
    "EURCAD": _forex_m, "EURCADm": _forex_m,
    "EURCHF": _forex_m, "EURCHFm": _forex_m,
    "EURNZD": _forex_m, "EURNZDm": _forex_m,
    "CADCHF": _forex_m, "CADCHFm": _forex_m,
    "NZDCAD": _forex_m, "NZDCADm": _forex_m,
    "USDSGD": _forex_m, "USDSGDm": _forex_m,
    "NZDJPY": _jpy_m,   "NZDJPYm": _jpy_m,
}
_spec = SYMBOL_SPECS.get(SYMBOL, {"spread": 1.0, "slippage": 0.5, "contract": 1.0})
SPREAD        = _spec["spread"]
SLIPPAGE      = _spec["slippage"]
CONTRACT_SIZE = _spec["contract"]


@dataclass
class BTTrade:
    role:        str
    direction:   str
    pattern:     str
    entry_time:  pd.Timestamp
    entry_price: float
    sl:          float
    tp:          float
    lot:         float
    target_price: Optional[float] = None      # role B only
    ema_trend_at_entry: float = 0.0           # for trend-flip monitor on A
    exit_time:   Optional[pd.Timestamp] = None
    exit_price:  Optional[float] = None
    exit_reason: Optional[str]   = None
    pnl_usd:     Optional[float] = None
    pnl_R:       Optional[float] = None


def fetch_range(symbol: str, tf: int, start: datetime, end: datetime) -> pd.DataFrame:
    rates = mt5.copy_rates_range(symbol, tf, start, end)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={"open":"Open","high":"High","low":"Low",
                       "close":"Close","tick_volume":"Volume"}, inplace=True)
    return df


def price_pnl(tr: BTTrade, exit_price: float) -> float:
    return (exit_price - tr.entry_price) if tr.direction == "BUY" \
           else (tr.entry_price - exit_price)


def to_usd(price_move: float, lot: float) -> float:
    return price_move * lot * CONTRACT_SIZE


def run_backtest(cfg: dict) -> List[BTTrade]:
    print(f"Fetching M15 data {START_DATE.date()} → {END_DATE.date()}...")
    df = fetch_range(SYMBOL, mt5.TIMEFRAME_M15, START_DATE, END_DATE)
    print(f"  M15: {len(df):>5} bars")
    if df.empty:
        return []

    entry_cfg  = cfg["entry"]
    dual       = cfg["dual_trade"]
    lot_a      = dual["trade_a_lot"]
    lot_b      = dual["trade_b_lot"]
    tp_b_usd   = dual["trade_b_profit_usd"]

    closed: List[BTTrade] = []
    open_t: List[BTTrade] = []
    last_exit_idx = -10**9
    cooldown_bars = entry_cfg.get("cooldown_bars", 0)

    # Need 200+ bars for EMA200 warmup; start at 210 to be safe
    start_i = max(210, entry_cfg.get("ema_trend", 200) + 10)
    total_bars = len(df) - 1
    print(f"\nReplaying bars {start_i}..{total_bars} ({total_bars - start_i} iterations)")
    progress_step = max(1, (total_bars - start_i) // 20)

    for i in range(start_i, total_bars):
        if (i - start_i) % progress_step == 0:
            pct = 100 * (i - start_i) / (total_bars - start_i)
            print(f"  {pct:>5.1f}% | bar {i}/{total_bars} | open {len(open_t)} | closed {len(closed)}")

        next_bar = df.iloc[i+1]
        nb_high  = float(next_bar["High"])
        nb_low   = float(next_bar["Low"])

        # ── Manage open trades against next bar ─────
        for tr in list(open_t):
            exit_price  = None
            exit_reason = None

            # 1. SL (worst case — checked first)
            if tr.direction == "BUY" and nb_low <= tr.sl:
                exit_price  = tr.sl - SLIPPAGE
                exit_reason = "SL"
            elif tr.direction == "SELL" and nb_high >= tr.sl:
                exit_price  = tr.sl + SLIPPAGE
                exit_reason = "SL"

            # 2. TP / B-target
            if exit_reason is None:
                if tr.role == "B" and tr.target_price is not None:
                    tp_px = tr.target_price
                    if tr.direction == "BUY" and nb_high >= tp_px:
                        exit_price = tp_px - SPREAD; exit_reason = "B_target"
                    elif tr.direction == "SELL" and nb_low <= tp_px:
                        exit_price = tp_px + SPREAD; exit_reason = "B_target"
                elif tr.role == "A":
                    if tr.direction == "BUY" and nb_high >= tr.tp:
                        exit_price = tr.tp - SPREAD; exit_reason = "TP"
                    elif tr.direction == "SELL" and nb_low <= tr.tp:
                        exit_price = tr.tp + SPREAD; exit_reason = "TP"

            # 3. Trend-flip early exit (A only)
            if exit_reason is None and tr.role == "A":
                if trend_flipped(df.iloc[:i+1], tr.direction,
                                 ema_trend_period=entry_cfg.get("ema_trend", 200),
                                 bar_idx=-1,
                                 chop_band_atr=entry_cfg.get("chop_band_atr", 0.5)):
                    exit_price = float(next_bar["Open"]) - SPREAD if tr.direction == "BUY" \
                                 else float(next_bar["Open"]) + SPREAD
                    exit_reason = "trend_flip"

            if exit_reason:
                tr.exit_time   = next_bar["time"]
                tr.exit_price  = exit_price
                tr.exit_reason = exit_reason
                pm = price_pnl(tr, exit_price)
                tr.pnl_usd = round(to_usd(pm, tr.lot), 4)
                sl_dist = abs(tr.entry_price - tr.sl)
                tr.pnl_R = round(pm / sl_dist, 3) if sl_dist > 0 else 0
                closed.append(tr)
                open_t.remove(tr)
                last_exit_idx = i

                # When B hits target, move A's SL to BE + small buffer.
                if tr.role == "B" and exit_reason == "B_target":
                    be_buffer = 2 * SPREAD
                    new_sl = tr.entry_price + be_buffer if tr.direction == "BUY" \
                             else tr.entry_price - be_buffer
                    for open_a in open_t:
                        if open_a.role == "A" and open_a.direction == tr.direction:
                            open_a.sl = new_sl
                            break

        # ── Look for new entries (only if no open trades and cooldown cleared) ──
        if open_t:
            continue
        if i - last_exit_idx <= cooldown_bars:   # cooldown after SL/TP/exit
            continue

        slice_to_now = df.iloc[:i+1]
        setup = find_entry(slice_to_now, entry_cfg, bar_idx=-1)
        if setup is None:
            continue

        # max_sl_usd cap
        max_sl_usd = entry_cfg.get("max_sl_usd", 0)
        if max_sl_usd > 0:
            sl_dist = abs(setup.entry_price - setup.sl)
            if sl_dist * lot_a * CONTRACT_SIZE > max_sl_usd:
                continue

        # Enter at next bar OPEN with spread
        entry_px = float(next_bar["Open"])
        ews = entry_px + SPREAD if setup.direction == "BUY" else entry_px - SPREAD

        a = BTTrade(
            role="A", direction=setup.direction, pattern=setup.pattern,
            entry_time=next_bar["time"], entry_price=ews,
            sl=setup.sl, tp=setup.tp, lot=lot_a,
            ema_trend_at_entry=setup.ema_trend,
        )
        open_t.append(a)

        if tp_b_usd > 0 and lot_b > 0:
            price_move_for_b = tp_b_usd / (lot_b * CONTRACT_SIZE)
            b_target = ews + price_move_for_b if setup.direction == "BUY" \
                       else ews - price_move_for_b
            b_max_loss = dual.get("trade_b_max_loss_usd", 5.0)
            struct_sl_dist = abs(ews - setup.sl)
            b_max_dist = b_max_loss / (lot_b * CONTRACT_SIZE) if b_max_loss > 0 \
                         else struct_sl_dist
            b_sl_dist = min(struct_sl_dist, b_max_dist)
            b_sl = (ews - b_sl_dist) if setup.direction == "BUY" else (ews + b_sl_dist)
            b = BTTrade(
                role="B", direction=setup.direction, pattern=setup.pattern,
                entry_time=next_bar["time"], entry_price=ews,
                sl=b_sl, tp=b_target, lot=lot_b, target_price=b_target,
                ema_trend_at_entry=setup.ema_trend,
            )
            open_t.append(b)

    # Period-end: force close any still-open
    for tr in open_t:
        final_close = float(df["Close"].iloc[-1])
        exit_px = final_close - SPREAD if tr.direction == "BUY" else final_close + SPREAD
        tr.exit_time   = df["time"].iloc[-1]
        tr.exit_price  = exit_px
        tr.exit_reason = "period_end"
        pm = price_pnl(tr, exit_px)
        tr.pnl_usd = round(to_usd(pm, tr.lot), 4)
        sl_dist = abs(tr.entry_price - tr.sl)
        tr.pnl_R = round(pm / sl_dist, 3) if sl_dist > 0 else 0
        closed.append(tr)

    return closed


def summarize(trades: List[BTTrade]):
    if not trades:
        print("\nNO TRADES generated during backtest period.")
        return

    print("\n" + "="*100)
    print(f"BACKTEST RESULTS — {len(trades)} trades from {trades[0].entry_time.date()} to {trades[-1].exit_time.date()}")
    print("="*100)

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

    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, {"n": 0, "pnl": 0})
        reasons[t.exit_reason]["n"] += 1
        reasons[t.exit_reason]["pnl"] += t.pnl_usd or 0
    print("\n  By exit reason:")
    for reason, s in sorted(reasons.items(), key=lambda kv: -kv[1]["pnl"]):
        print(f"    {reason:<22} {s['n']:>3} trades  | total ${s['pnl']:+.2f}")

    patterns = {}
    for t in trades:
        if t.role != "A": continue
        patterns[t.pattern] = patterns.get(t.pattern, {"n": 0, "wins": 0, "pnl": 0})
        patterns[t.pattern]["n"] += 1
        if (t.pnl_usd or 0) > 0: patterns[t.pattern]["wins"] += 1
        patterns[t.pattern]["pnl"] += t.pnl_usd or 0
    print("\n  By pattern (Trade A only):")
    for p, s in patterns.items():
        wr = s["wins"]/s["n"]*100 if s["n"] else 0
        print(f"    {p:<22} {s['n']:>3} trades  | WR {wr:.1f}% | NET ${s['pnl']:+.2f}")

    months = {}
    for t in trades:
        key = f"{t.entry_time.year}-{t.entry_time.month:02d}"
        months[key] = months.get(key, {"n": 0, "pnl": 0, "wins": 0})
        months[key]["n"] += 1
        months[key]["pnl"] += t.pnl_usd or 0
        if (t.pnl_usd or 0) > 0: months[key]["wins"] += 1
    print("\n  By month:")
    for key in sorted(months.keys()):
        s = months[key]
        wr = s["wins"]/s["n"]*100 if s["n"] else 0
        print(f"    {key}  {s['n']:>3} trades  | WR {wr:.1f}% | NET ${s['pnl']:+.2f}")

    # Equity / drawdown
    equity = 0; peak = 0; max_dd = 0
    for t in sorted(trades, key=lambda x: x.exit_time):
        equity += t.pnl_usd or 0
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    total_net = sum(t.pnl_usd or 0 for t in trades)
    days = max(1, (trades[-1].exit_time - trades[0].entry_time).days)
    print("\n" + "-"*100)
    print(f"  TOTAL NET P/L:     ${total_net:+.2f}")
    print(f"  Max drawdown:      ${max_dd:+.2f}")
    print(f"  Trades per week:   {len(trades) / (days / 7):.2f}")


def main():
    if not connect(): return
    mt5.symbol_select(SYMBOL, True)
    cfg = MARKETS.get(SYMBOL)
    if cfg is None:
        for k, v in MARKETS.items():
            if SYMBOL in v.get("symbol_candidates", []):
                cfg = v
                break
    if cfg is None:
        print(f"No config found for {SYMBOL}")
        disconnect(); return
    print(f"\nConfig: strategy={cfg['strategy']}  "
          f"lot_A={cfg['dual_trade']['trade_a_lot']}  "
          f"lot_B={cfg['dual_trade']['trade_b_lot']}  "
          f"tp_B=${cfg['dual_trade']['trade_b_profit_usd']}")
    print(f"Spread modeled: ${SPREAD}  |  Slippage: ${SLIPPAGE}  |  Contract: {CONTRACT_SIZE}")
    trades = run_backtest(cfg)
    summarize(trades)
    disconnect()


if __name__ == "__main__":
    main()