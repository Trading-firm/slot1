"""
database/models.py
──────────────────
MongoDB setup for the trading bot.
Collections:
  - trades        : Every trade executed (open + closed)
  - signals       : Every signal generated (acted on or not)
  - daily_summary : End-of-day performance snapshot
  - bot_state     : Persistent key-value bot state
"""

from datetime import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
import certifi
from config.settings import settings
from utils.logger import logger


def get_db():
    """Return the trading_bot MongoDB database instance."""
    # Handle SSL errors by optionally disabling verification (common on Windows VPS)
    import certifi
    try:
        client = MongoClient(settings.MONGO_URI, tlsCAFile=certifi.where())
    except Exception:
        # Fallback for some Windows environments
        client = MongoClient(settings.MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
        
    return client[settings.MONGO_DB_NAME]


def init_db():
    """
    Initialise collections and indexes.
    Safe to call multiple times.
    """
    try:
        db = get_db()

        # trades
        db.trades.create_index([("status", ASCENDING)])
        db.trades.create_index([("pair", ASCENDING)])
        db.trades.create_index([("entry_time", DESCENDING)])

        # signals
        db.signals.create_index([("pair", ASCENDING)])
        db.signals.create_index([("created_at", DESCENDING)])

        # daily_summary
        db.daily_summary.create_index([("date", ASCENDING)], unique=True)

        # bot_state
        db.bot_state.create_index([("key", ASCENDING)], unique=True)

        logger.info("MongoDB initialised successfully.")

    except Exception as e:
        logger.error(f"Failed to initialise MongoDB: {e}")
        raise


# ─── Collection Accessors ─────────────────────────────────
def trades_col() -> Collection:
    return get_db().trades

def signals_col() -> Collection:
    return get_db().signals

def daily_summary_col() -> Collection:
    return get_db().daily_summary

def bot_state_col() -> Collection:
    return get_db().bot_state
