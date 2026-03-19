"""
config/settings.py
──────────────────
Central configuration loader.
All settings are read from the .env file.
Never hardcode secrets in source code.
"""

import os
from dotenv import load_dotenv

# Load .env file
if not load_dotenv():
    print("WARNING: .env file not found! Using default settings.")
else:
    print(f"INFO: Loaded .env file. MONGO_URI starts with: {os.getenv('MONGO_URI', '')[:15]}...")


class Settings:
    # ─── Broker ──────────────────────────────────────────
    EXCHANGE_ID: str         = os.getenv("EXCHANGE_ID", "deriv")
    EXCHANGE_API_KEY: str    = os.getenv("EXCHANGE_API_KEY", "")
    EXCHANGE_API_SECRET: str = os.getenv("EXCHANGE_API_SECRET", "")
    EXCHANGE_SANDBOX: bool   = os.getenv("EXCHANGE_SANDBOX", "true").lower() == "true"

    # ─── MetaTrader 5 ─────────────────────────────────────
    MT5_LOGIN: int           = int(os.getenv("MT5_LOGIN") or 0)
    MT5_PASSWORD: str        = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str          = os.getenv("MT5_SERVER", "")
    MT5_PATH: str            = os.getenv("MT5_PATH", "")  # Optional path to terminal.exe

    # ─── MongoDB ──────────────────────────────────────────
    MONGO_URI: str      = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME: str  = os.getenv("MONGO_DB_NAME", "trading_bot")

    # ─── Trading ──────────────────────────────────────────
    # Refined list based on Win Rate Analysis (>60% success)
    TRADING_PAIRS: list  = [
        "BTC/USD", "USD/JPY", "Volatility 100 Index", 
        "Volatility 25 Index", "AUD/USD", "XAU/USD", "GBP/USD"
    ]
    TIMEFRAME: str       = os.getenv("TIMEFRAME", "1h")
    TRADE_MODE: str      = os.getenv("TRADE_MODE", "live")

    # ─── Risk Management ──────────────────────────────────
    RISK_PER_TRADE: float    = float(os.getenv("RISK_PER_TRADE", 0.01))
    MAX_OPEN_TRADES: int     = int(os.getenv("MAX_OPEN_TRADES", 0))
    
    # Momentum-Based Active Monitoring
    # Once trade reaches this percentage of the TP distance, start monitoring closely
    BREAKEVEN_ARM_PCT: float = float(os.getenv("BREAKEVEN_ARM_PCT", 0.50))
    MOMENTUM_EXIT_ARM_PCT: float = float(os.getenv("MOMENTUM_EXIT_ARM_PCT", 0.70))
    MOMENTUM_EXIT_EMA_REVERSAL: bool = os.getenv("MOMENTUM_EXIT_EMA_REVERSAL", "true").lower() == "true"

    # Strategic Stop Loss placement (ATR Buffer)
    ATR_MULTIPLIER_SL: float = float(os.getenv("ATR_MULTIPLIER_SL", 1.5))
    # Flexible TP (Wider target, but active exit)
    ATR_MULTIPLIER_TP: float = float(os.getenv("ATR_MULTIPLIER_TP", 5.0))

    # Maximum allowable SL distance in % (to prevent huge drawdowns)
    MAX_SL_DISTANCE_PCT: float = float(os.getenv("MAX_SL_DISTANCE_PCT", 0.05))

    # Asset-Specific SL Settings
    SL_PCT_FOREX: float   = float(os.getenv("SL_PCT_FOREX", 0.002))
    SL_PCT_INDICES: float = float(os.getenv("SL_PCT_INDICES", 0.01))

    # TP Settings (Calculated as SL_Dist * REWARD_RATIO or Fixed ATR)
    TP_MIN_PCT: float = float(os.getenv("TP_MIN_PCT", 0.003))
    TP_MAX_PCT: float = float(os.getenv("TP_MAX_PCT", 0.15))
    
    # Asset-Specific TP Min
    TP_MIN_PCT_FOREX: float   = float(os.getenv("TP_MIN_PCT_FOREX", 0.002))
    TP_MIN_PCT_INDICES: float = float(os.getenv("TP_MIN_PCT_INDICES", 0.004))
    
    # Standard ATR Multiplier for legacy support
    STANDARD_SL_ATR: float = float(os.getenv("STANDARD_SL_ATR", 1.5))
    RISK_REWARD_RATIO: float = float(os.getenv("RISK_REWARD_RATIO", 2.0))
    REWARD_RATIO: float = float(os.getenv("REWARD_RATIO", 2.0))

    # Volatility 25 Index Specific Settings
    VOL25_SL_ATR_MULT: float = float(os.getenv("VOL25_SL_ATR_MULT", 1.2))
    VOL25_TP_ATR_MULT: float = float(os.getenv("VOL25_TP_ATR_MULT", 1.5))

    # Volatility 75 Index Specific Settings
    VOL75_SL_ATR_MULT: float = float(os.getenv("VOL75_SL_ATR_MULT", 1.5))
    VOL75_TP_ATR_MULT: float = float(os.getenv("VOL75_TP_ATR_MULT", 1.5))

    # Volatility 10 Index Specific Settings
    VOL10_SL_ATR_MULT: float = float(os.getenv("VOL10_SL_ATR_MULT", 1.5))
    VOL10_TP_ATR_MULT: float = float(os.getenv("VOL10_TP_ATR_MULT", 1.5))
    
    MAX_DAILY_LOSS: float    = float(os.getenv("MAX_DAILY_LOSS", 0.05))
    MAX_DAILY_LOSS_USD: float = float(os.getenv("MAX_DAILY_LOSS_USD", 0.0))
    
    # ─── Entry Confirmation ───────────────────────────────
    # Max Spread Ratio: Spread must be less than 20% of the Potential Profit (TP Distance)
    # This protects small wins from being eaten by spread costs.
    MAX_SPREAD_PROFIT_RATIO: float = float(os.getenv("MAX_SPREAD_PROFIT_RATIO", 0.2))
    
    # ADX Filter: Only enter if trend strength is > 20 (Avoids chop)
    MIN_ADX_STRENGTH: float = float(os.getenv("MIN_ADX_STRENGTH", 20.0))

    # ─── Strategy ─────────────────────────────────────────
    ENABLE_CONFLUENCE: bool = False

    MIN_CONFLUENCE: int     = 1

    EMA_FAST: int    = 20
    EMA_SLOW: int    = 50
    RSI_PERIOD: int  = 14
    RSI_UPPER: float = 70
    RSI_LOWER: float = 30
    ATR_PERIOD: int  = 14
    
    EMA_TREND_PERIOD: int = 200
    ADX_THRESHOLD: float  = 25.0

    # ─── Strategy Mapping ─────────────────────────────────
    # Maps specific pairs to a list of strategy configurations
    # Each entry contains the strategy name and the timeframe it should run on
    STRATEGY_CONFIG: dict = {
        'default': [
            {'strategy': 'trend_following', 'timeframe': '1h'}
        ]
    }

    # ─── Scheduler ────────────────────────────────────────
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", 15))

    # ─── Logging ──────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str  = os.getenv("LOG_FILE", "logs/trading_bot.log")

    # ─── Notifications ────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str   = os.getenv("TELEGRAM_CHAT_ID", "")


settings = Settings()
