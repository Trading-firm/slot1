"""
scheduler/runner.py
────────────────────
APScheduler runner — fires the engine every CHECK_INTERVAL_SECONDS.
Handles graceful shutdown on Ctrl+C.
"""

import time
import signal
import sys
from apscheduler.schedulers.background import BackgroundScheduler
from scheduler.engine import TradingEngine
from config.settings import settings
from utils.logger import logger


def start():
    engine    = TradingEngine()
    scheduler = BackgroundScheduler()

    # Run immediately on startup
    engine.run_cycle()

    scheduler.add_job(
        func          = engine.run_cycle,
        trigger       = "interval",
        seconds       = settings.CHECK_INTERVAL_SECONDS,
        id            = "trading_cycle",
        max_instances = 1,
        coalesce      = True,
    )
    scheduler.start()

    logger.info(
        f"Scheduler running — cycle every "
        f"{settings.CHECK_INTERVAL_SECONDS}s | Press Ctrl+C to stop"
    )

    def shutdown(sig, frame):
        logger.info("Shutdown signal received — stopping bot...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        time.sleep(1)
