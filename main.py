"""
main.py
────────
Entry point for the Unified Trading Bot.

Commands:
  python main.py run      — Start live trading
  python main.py status   — Show open trades and daily performance
  python main.py markets  — Show all active market configurations
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import logger
from config.settings import settings
from config.markets import MARKETS


def run():
    logger.info("=" * 70)
    logger.info("  UNIFIED TRADING BOT — STARTING")
    logger.info(f"  Markets    : {len(MARKETS)} active")
    for name, cfg in MARKETS.items():
        entry = cfg.get("entry", {})
        sessions = entry.get("sessions", [])
        sess_str = ",".join(f"{s[0]:02d}-{s[1]:02d}" for s in sessions) or "24/7"
        preset   = cfg.get("strategy_preset", "?")
        lot      = cfg.get("dual_trade", {}).get("trade_a_lot", "?")
        logger.info(
            f"  {name:<8} | M15 | preset={preset:<13} | rr={entry.get('min_rr',0):.1f} | "
            f"sess={sess_str:<11} | lot={lot} | max_sl=${entry.get('max_sl_usd',0):.1f}"
        )
    logger.info(f"  Risk/Trade : {settings.RISK_PER_TRADE*100:.1f}%")
    logger.info(f"  Max Trades : {settings.MAX_OPEN_TRADES}")
    logger.info(f"  Daily Stop : {settings.MAX_DAILY_LOSS*100:.1f}%")
    logger.info(f"  Interval   : {settings.CHECK_INTERVAL_SECONDS}s")
    logger.info("=" * 70)

    from scheduler.runner import start
    start()


def status():
    from database.firebase import init_db
    from database.repository import TradeRepo, SummaryRepo, PerfRepo
    from broker.mt5_connector import connect, get_balance, disconnect

    init_db()
    connect()
    balance = get_balance()
    disconnect()

    open_trades  = TradeRepo.get_open_trades()
    daily_trades = TradeRepo.get_trades_today()
    daily_pnl    = TradeRepo.get_daily_pnl()
    perfs        = PerfRepo.get_all()

    daily_wins = sum(t["pnl"] for t in daily_trades if t.get("pnl", 0) > 0)
    daily_loss = sum(t["pnl"] for t in daily_trades if t.get("pnl", 0) <= 0)
    starting_bal  = balance - daily_pnl
    daily_pnl_pct = (daily_pnl / starting_bal * 100) if starting_bal > 0 else 0

    print("\n" + "=" * 70)
    print("  UNIFIED BOT STATUS")
    print("=" * 70)
    print(f"  Balance      : ${balance:.2f}")
    print(f"  Daily PnL    : {daily_pnl_pct:+.2f}% (${daily_pnl:+.4f})")
    print(f"  Daily Wins   : ${daily_wins:.4f}")
    print(f"  Daily Losses : ${daily_loss:.4f}")
    print(f"  Open Trades  : {len(open_trades)}/{settings.MAX_OPEN_TRADES}")
    print("-" * 70)

    if open_trades:
        for t in open_trades:
            print(
                f"  {t['symbol']:<25} | {t['direction']:<5} | "
                f"Entry: {t['entry_price']:.5f} | "
                f"SL: {t['sl']:.5f} | TP: {t['tp']:.5f}"
            )
    else:
        print("  No open trades.")

    print("-" * 70)
    print("  MARKET PERFORMANCE (ALL TIME)")
    print("-" * 70)
    if perfs:
        for p in perfs:
            total = p.get("total_trades", 0)
            wins  = p.get("wins", 0)
            wr    = round(wins / total * 100, 1) if total > 0 else 0
            print(
                f"  {p['symbol']:<25} | "
                f"Trades: {total:>4} | "
                f"Win Rate: {wr:>5.1f}% | "
                f"PnL: ${p.get('total_pnl', 0):.4f}"
            )
    else:
        print("  No performance data yet.")

    print("=" * 70 + "\n")


def show_markets():
    print("\n" + "=" * 80)
    print("  ACTIVE MARKET CONFIGURATIONS — Trend-Follower")
    print("=" * 80)
    for name, cfg in MARKETS.items():
        entry = cfg.get("entry", {})
        sessions = entry.get("sessions", [])
        sess_str = ", ".join(f"{s[0]:02d}h-{s[1]:02d}h UTC" for s in sessions) if sessions else "24/7"
        patterns = ", ".join(entry.get("required_pattern", []) or ["all"])
        print(
            f"\n  {name}  ({cfg.get('strategy_preset', '?')})\n"
            f"    Timeframe       : {cfg['tf_name']}\n"
            f"    EMA trend / pull: {entry.get('ema_trend')} / {entry.get('ema_pullback')}\n"
            f"    Min R:R         : {entry.get('min_rr')}\n"
            f"    Patterns        : {patterns}\n"
            f"    Sessions        : {sess_str}\n"
            f"    Max SL ($)      : {entry.get('max_sl_usd')}\n"
            f"    Lot             : {cfg.get('dual_trade', {}).get('trade_a_lot')}"
        )
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "status":
        status()
    elif cmd == "markets":
        show_markets()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python main.py [run|status|markets]")
        sys.exit(1)
