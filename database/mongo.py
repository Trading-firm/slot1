"""
database/mongo.py
──────────────────
MongoDB connection and collection accessors.
"""
from pymongo import MongoClient, ASCENDING, DESCENDING
from config.settings import settings
from utils.logger import logger

try:
    import certifi
    ca = certifi.where()
except ImportError:
    ca = None

def get_db():
    if ca:
        client = MongoClient(settings.MONGO_URI, tlsCAFile=ca)
    else:
        client = MongoClient(settings.MONGO_URI)
    return client[settings.MONGO_DB_NAME]


def init_db():
    try:
        db = get_db()

        # trades
        db.trades.create_index([("status",     ASCENDING)])
        db.trades.create_index([("symbol",     ASCENDING)])
        db.trades.create_index([("ticket",     ASCENDING)], unique=True, sparse=True)
        db.trades.create_index([("entry_time", DESCENDING)])

        # daily_summary
        db.daily_summary.create_index([("date", ASCENDING)], unique=True)

        # bot_state
        db.bot_state.create_index([("key", ASCENDING)], unique=True)

        # market_performance
        db.market_performance.create_index([("symbol", ASCENDING)])

        logger.info("MongoDB initialised successfully.")
    except Exception as e:
        logger.error(f"MongoDB init failed: {e}")
        raise


def trades_col():      return get_db().trades
def summary_col():     return get_db().daily_summary
def state_col():       return get_db().bot_state
def perf_col():        return get_db().market_performance
