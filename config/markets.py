"""
config/markets.py
─────────────────
Top 10 markets — selected by 60-day backtest win rate.
Strategy: Trend-Following — EMA20 pullback + ADX + RSI + HTF confirmation.
One trade per signal at 1:1 R:R. Break-even triggers at 0.5× ATR profit.

Win rates (60-day backtest, 1:1 R:R):
  Volatility 100 Index : 69.6% | M30 ADX>=25 London+US
  Crash 1000 Index     : 76.9% | M15 ADX>=25 London
  XAGUSD               : 75.0% | H1  ADX>=25 24/7
  Boom 1000 Index      : 73.3% | M15 ADX>=30 24/7
  XRPUSD               : 63.3% | M15 ADX>=25 London
  AUDJPY               : 66.7% | M30 ADX>=25 London
  GBPJPY               : 65.2% | M15 ADX>=25 London
  EURJPY               : 61.1% | M30 ADX>=25 London+US
  XAUUSD               : 61.1% | H1  ADX>=25 London+US
  GBPCAD               : 60.5% | M15 ADX>=20 US

All sessions in WAT (UTC+1).
MAX_OPEN_TRADES = 10 markets × 1 order = 10
"""
import MetaTrader5 as mt5

MARKETS = {

    # ── Volatility 100 Index ── 69.6% | M30 | ADX>=25 | London+US ───────────
    "Volatility 100 Index": {
        "symbol":     "Volatility 100 Index",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8,  "end": 17},   # London
                {"start": 15, "end": 23},   # US
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      1.0,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── Crash 1000 Index ── 76.9% | M15 | ADX>=25 | London ──────────────────
    "Crash 1000 Index": {
        "symbol":     "Crash 1000 Index",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8, "end": 17},    # London
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.2,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── XAGUSD ── 75.0% | H1 | ADX>=25 | 24/7 ───────────────────────────────
    "XAGUSD": {
        "symbol":     "XAGUSD",
        "timeframe":  mt5.TIMEFRAME_H1,
        "tf_name":    "H1",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions":      [],            # 24/7 — no session filter
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── Boom 1000 Index ── 73.3% | M15 | ADX>=30 | 24/7 ─────────────────────
    "Boom 1000 Index": {
        "symbol":     "Boom 1000 Index",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       30,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions":      [],            # 24/7 — no session filter
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.2,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── XRPUSD ── 63.3% | M15 | ADX>=25 | London ─────────────────────────────
    "XRPUSD": {
        "symbol":     "XRPUSD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8, "end": 17},    # London
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      500.0,  # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── AUDJPY ── 66.7% | M30 | ADX>=25 | London ─────────────────────────────
    "AUDJPY": {
        "symbol":     "AUDJPY",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8, "end": 17},    # London
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── GBPJPY ── 65.2% | M15 | ADX>=25 | London ─────────────────────────────
    "GBPJPY": {
        "symbol":     "GBPJPY",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8, "end": 17},    # London
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── EURJPY ── 61.1% | M30 | ADX>=25 | London+US ──────────────────────────
    "EURJPY": {
        "symbol":     "EURJPY",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8,  "end": 17},   # London
                {"start": 15, "end": 23},   # US
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── XAUUSD ── 61.1% | H1 | ADX>=25 | London+US ───────────────────────────
    "XAUUSD": {
        "symbol":     "XAUUSD",
        "timeframe":  mt5.TIMEFRAME_H1,
        "tf_name":    "H1",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":      20,
            "ema_slow":      50,
            "ema_trend":     200,
            "adx_period":    14,
            "adx_min":       25,
            "rsi_min_buy":   35,
            "rsi_max_buy":   58,
            "rsi_min_sell":  42,
            "rsi_max_sell":  65,
            "sessions": [
                {"start": 8,  "end": 17},   # London
                {"start": 15, "end": 23},   # US
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── GBPCAD ── 60.5% | M15 | ADX>=20 | US ─────────────────────────────────
    "GBPCAD": {
        "symbol":     "GBPCAD",
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
                {"start": 15, "end": 23},   # US
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },
}