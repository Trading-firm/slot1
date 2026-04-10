"""
config/settings.py
──────────────────
All bot configuration loaded from .env
"""
import os
from dotenv import load_dotenv
load_dotenv()

class Settings:
    # ─── Broker ──────────────────────────────────────────
    MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 0))
    MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER   = os.getenv("MT5_SERVER", "Deriv-Demo")

    # ─── Firebase ────────────────────────────────────────
    FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "firebase-credentials.json")

    # ─── Risk Management ─────────────────────────────────
    RISK_PER_TRADE    = float(os.getenv("RISK_PER_TRADE",    0.01))  # 1% per trade
    MAX_OPEN_TRADES   = int(os.getenv("MAX_OPEN_TRADES",     12))    # 3 per market for 4 markets
    MAX_DAILY_LOSS    = float(os.getenv("MAX_DAILY_LOSS",    0.05))  # 5% daily stop
    MIN_LOT_SIZE      = float(os.getenv("MIN_LOT_SIZE",      0.01))  # Deriv minimum
    MAX_LOT_SIZE      = float(os.getenv("MAX_LOT_SIZE",      1.0))

    # ─── Scheduler ───────────────────────────────────────
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", 60))

    # ─── Logging ─────────────────────────────────────────
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE  = os.getenv("LOG_FILE",  "logs/unified_bot.log")

settings = Settings()
