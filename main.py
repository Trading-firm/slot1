"""
main.py
────────
Entry point for the trading bot.

Commands:
  python main.py run        — Start the live/paper trading bot
  python main.py backtest   — Run backtest on all configured pairs
  python main.py status     — Show current open trades and daily summary
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import logger
from config.settings import settings


def run_bot():
    logger.info("=" * 60)
    logger.info("  TRADING BOT STARTING")
    logger.info(f"  Mode      : {settings.TRADE_MODE.upper()}")
    logger.info(f"  Exchange  : {settings.EXCHANGE_ID}")
    logger.info(f"  Pairs     : {', '.join(settings.TRADING_PAIRS)}")
    logger.info(f"  Timeframe : {settings.TIMEFRAME}")
    logger.info(f"  Interval  : every {settings.CHECK_INTERVAL_MINUTES} min")
    logger.info(f"  Risk/Trade: {settings.RISK_PER_TRADE * 100:.1f}%")
    logger.info(f"  Max Trades: {settings.MAX_OPEN_TRADES}")
    logger.info("=" * 60)

    if settings.TRADE_MODE == "live" and not settings.EXCHANGE_SANDBOX:
        logger.warning("⚠️  LIVE TRADING MODE — real money will be used!")
        confirm = input("Type 'YES' to confirm live trading: ")
        if confirm.strip() != "YES":
            logger.info("Live trading cancelled.")
            sys.exit(0)

    from scheduler.runner import start_scheduler
    start_scheduler()


def run_backtest():
    from backtester.backtest import run_backtest as bt
    results = []
    for pair in settings.TRADING_PAIRS:
        result = bt(pair=pair, timeframe=settings.TIMEFRAME)
        if result:
            results.append(result)

    if len(results) > 1:
        print("\n" + "=" * 60)
        print("  COMBINED BACKTEST SUMMARY")
        print("=" * 60)
        for r in results:
            print(
                f"  {r['pair']:<10} | Profit: {r['profit_pct']:>7.2f}% | "
                f"Trades: {r['total_trades']:>4} | Win Rate: {r['win_rate']:>5.1f}%"
            )
        print("=" * 60)


def show_status():
    from database.models import init_db
    from database.repository import TradeRepository, DailySummaryRepository
    from datetime import date

    init_db()

    open_trades = TradeRepository.get_open_trades()
    daily_pnl   = TradeRepository.get_daily_pnl()

    print("\n" + "=" * 60)
    print("  TRADING BOT STATUS")
    print("=" * 60)
    print(f"  Mode        : {settings.TRADE_MODE.upper()}")
    print(f"  Exchange    : {settings.EXCHANGE_ID}")
    print(f"  Date        : {date.today()}")
    print(f"  Daily PnL   : ${daily_pnl:.2f}")
    print(f"  Open Trades : {len(open_trades)}")
    print("-" * 60)

    if open_trades:
        for t in open_trades:
            print(
                f"  {t['pair']:<10} {t['direction']:<5} | "
                f"Entry: {t['entry_price']:.5f} | "
                f"SL: {t['stop_loss']:.5f} | "
                f"TP: {t['take_profit']:.5f}"
            )
    else:
        print("  No open trades.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"

    if command == "run":
        run_bot()
    elif command == "backtest":
        run_backtest()
    elif command == "status":
        show_status()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python main.py [run|backtest|status]")
        sys.exit(1)
