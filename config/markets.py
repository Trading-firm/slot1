"""
config/markets.py
─────────────────
Symbol configurations. All backtested on 60 days of real MT5 data.
Strategy: Trend-Following — EMA pullback + RSI + candlestick confirmation.

Win rates (60-day backtest at TP1 1:1, actual 3-TP system averages ~2R per win):
  EURUSD : 56.7% | M15 ADX>=20 US session
  GBPUSD : 53.1% | M15 ADX>=20 US session
  USDJPY : 57.1% | M30 ADX>=20 London session
  Vol75  : 61.9% | M30 ADX>=25 US session
  BTCUSD : 57.7% | M30 ADX>=20 London session

All sessions in WAT (UTC+1).
"""
import MetaTrader5 as mt5

MARKETS = {
    # ── EURUSD ── 56.7% win rate | M15 | ADX>=20 | US session ──────────────
    "EURUSD": {
        "symbol":     "EURUSD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       20,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 15, "end": 23},   # US session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── GBPUSD ── 53.1% win rate | M15 | ADX>=20 | US session ──────────────
    "GBPUSD": {
        "symbol":     "GBPUSD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       20,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 15, "end": 23},   # US session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── USDJPY ── 57.1% win rate | M30 | ADX>=20 | London session ───────────
    "USDJPY": {
        "symbol":     "USDJPY",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       20,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8,  "end": 17},   # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── Volatility 75 ── 61.9% win rate | M30 | ADX>=25 | US session ────────
    "Volatility 75 Index": {
        "symbol":     "Volatility 75 Index",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,    # Higher threshold — M15 fails badly on Vol75
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 15, "end": 23},   # US session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,      # Vol75 min lot is 0.001
        "atr_period":   14,
    },

    # ── BTCUSD ── 57.7% win rate | M30 | ADX>=20 | London session ───────────
    # Backtest: M15+US/Asian = 48.9% (-1R). M30+London = 57.7% (+19R 3-TP).
    # London session is where BTC trends cleanly; US/Asian sessions lose.
    "BTCUSD": {
        "symbol":     "BTCUSD",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       20,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },
}
