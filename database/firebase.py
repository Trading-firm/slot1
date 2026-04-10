"""
database/firebase.py
─────────────────────
Firebase Firestore connection and collection accessors.

Setup:
  1. Go to Firebase Console → Project Settings → Service Accounts
  2. Click "Generate new private key" → download the JSON file
  3. Save it to this project folder (e.g. firebase-credentials.json)
  4. Set FIREBASE_CREDENTIALS=firebase-credentials.json in .env
"""
import firebase_admin
from firebase_admin import credentials, firestore
from config.settings import settings
from utils.logger import logger

_initialized = False


def _ensure_init():
    global _initialized
    if not _initialized:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS)
        firebase_admin.initialize_app(cred)
        _initialized = True


def get_db():
    _ensure_init()
    return firestore.client()


def init_db():
    try:
        _ensure_init()
        db = get_db()
        # Firestore creates collections automatically — just verify connection
        db.collection("trades").limit(1).get()
        logger.info("Firebase Firestore initialised successfully.")
    except Exception as e:
        logger.error(f"Firebase init failed: {e}")
        raise


def trades_col():   return get_db().collection("trades")
def summary_col():  return get_db().collection("daily_summary")
def state_col():    return get_db().collection("bot_state")
def perf_col():     return get_db().collection("market_performance")