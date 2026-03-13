"""
scheduler/runner.py
────────────────────
APScheduler wrapper.
Runs the trading engine at the configured interval.
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from scheduler.engine import TradingEngine
from config.settings import settings
from utils.logger import logger
import signal
import sys


def start_scheduler():
    """Start the trading bot scheduler."""
    engine    = TradingEngine()
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        func    = engine.run_cycle,
        trigger = IntervalTrigger(minutes=settings.CHECK_INTERVAL_MINUTES),
        id      = "trading_cycle",
        name    = "Trading Engine Cycle",
        replace_existing = True,
        max_instances    = 1,       # Never run two cycles simultaneously
    )

    # Graceful shutdown on Ctrl+C or SIGTERM
    def shutdown(signum, frame):
        logger.info("Shutdown signal received. Stopping scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info(
        f"Scheduler started. Running every {settings.CHECK_INTERVAL_MINUTES} minute(s). "
        f"Press Ctrl+C to stop."
    )

    # Run once immediately on startup before waiting for first interval
    logger.info("Running initial cycle on startup...")
    engine.run_cycle()

    scheduler.start()
