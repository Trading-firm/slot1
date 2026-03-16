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
    TRADING_PAIRS: list  = [p.strip() for p in os.getenv("TRADING_PAIRS", "EUR/USD,GBP/USD").split(",")]
    TIMEFRAME: str       = os.getenv("TIMEFRAME", "1h")
    TRADE_MODE: str      = os.getenv("TRADE_MODE", "paper")

    # ─── Risk Management ──────────────────────────────────
    RISK_PER_TRADE: float    = float(os.getenv("RISK_PER_TRADE", 0.01))
    MAX_OPEN_TRADES: int     = int(os.getenv("MAX_OPEN_TRADES", 3))
    
    # Standard Risk:Reward Ratio (1:1 for Small Wins/Scalping)
    # Reduced from 2.0 to 1.0 to ensure closer TP targets
    RISK_REWARD_RATIO: float = float(os.getenv("RISK_REWARD_RATIO", 1.0))

    # Standard ATR Multiplier for SL (High Probability placement)
    # 1.5 ATR is a standard tight-but-safe distance.
    STANDARD_SL_ATR: float = float(os.getenv("STANDARD_SL_ATR", 1.5))

    # Dynamic TP & Fixed SL Settings
    # Default fallback (if not matched below)
    SL_PCT: float = float(os.getenv("SL_PCT", 0.01))
    
    # Asset-Specific SL Settings
    # Forex needs tighter SL (0.2% ~ 20 pips) to allow realistic lot sizes on small accounts
    SL_PCT_FOREX: float   = float(os.getenv("SL_PCT_FOREX", 0.002))
    # Indices need wider SL (1.0%) due to high volatility
    SL_PCT_INDICES: float = float(os.getenv("SL_PCT_INDICES", 0.01))

    # TP is dynamic based on ATR but clamped
    TP_MIN_PCT: float = float(os.getenv("TP_MIN_PCT", 0.001)) # Reduced to 0.1%
    TP_MAX_PCT: float = float(os.getenv("TP_MAX_PCT", 0.01))
    
    # Asset-Specific TP Min (Forex can take smaller profits)
    TP_MIN_PCT_FOREX: float   = float(os.getenv("TP_MIN_PCT_FOREX", 0.001))
    TP_MIN_PCT_INDICES: float = float(os.getenv("TP_MIN_PCT_INDICES", 0.002))
    
    # ATR Multiplier for "Raw" TP calculation (before clamping)
    # Reduced from 2.0 to 1.0 to be closer to entry
    ATR_MULTIPLIER_TP: float = float(os.getenv("ATR_MULTIPLIER_TP", 1.0))
    ATR_MULTIPLIER_SL: float = float(os.getenv("ATR_MULTIPLIER_SL", 1.5))

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
    ENABLE_CONFLUENCE: bool = os.getenv("ENABLE_CONFLUENCE", "true").lower() == "true"
    MIN_CONFLUENCE: int     = int(os.getenv("MIN_CONFLUENCE", 1))

    EMA_FAST: int    = int(os.getenv("EMA_FAST", 9))
    EMA_SLOW: int    = int(os.getenv("EMA_SLOW", 21))
    RSI_PERIOD: int  = int(os.getenv("RSI_PERIOD", 14))
    RSI_UPPER: float = float(os.getenv("RSI_UPPER", 50))
    RSI_LOWER: float = float(os.getenv("RSI_LOWER", 50))
    ATR_PERIOD: int  = int(os.getenv("ATR_PERIOD", 14))
    
    EMA_TREND_PERIOD: int = int(os.getenv("EMA_TREND_PERIOD", 200))
    ADX_THRESHOLD: float  = float(os.getenv("ADX_THRESHOLD", 25.0))

    # ─── Strategy Mapping ─────────────────────────────────
    # Maps specific pairs to a list of strategy configurations
    # Each entry contains the strategy name and the timeframe it should run on
    STRATEGY_CONFIG: dict = {
    'Volatility 10 Index': {
            "strategies": [
                {'strategy': 'rsi_stoch', 'timeframe': '30m'},
            ],
            "min_confluence": 1
        },
        'Volatility 25 Index': {
            "strategies": [
                {'strategy': 'mean_reversion', 'timeframe': '4h'},
                {'strategy': 'cci_trend', 'timeframe': '30m'},
            ],
            "min_confluence": 1
        },
        'Volatility 75 Index': {
            "strategies": [
                {'strategy': 'cci_trend', 'timeframe': '1h'},
                {'strategy': 'support_resistance', 'timeframe': '4h'},
            ],
            "min_confluence": 1
        },
        'Volatility 100 Index': {
            "strategies": [
                {'strategy': 'rsi_stoch', 'timeframe': '1h'},
                {'strategy': 'cci_trend', 'timeframe': '1h'},
            ],
            # Confluence of 2 for higher probability
            "min_confluence": 1
        },
        'default': [
            {'strategy': 'bollinger_breakout', 'timeframe': '1h'},
            {'strategy': 'macd_cross', 'timeframe': '1h'}
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
