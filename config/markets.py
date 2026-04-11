"""
config/markets.py
─────────────────
Symbol configurations. All backtested on 60 days of real MT5 data.
Strategy: Trend-Following — EMA pullback + RSI + candlestick confirmation.

Win rates (60-day backtest at TP1 1:1, actual 3-TP system averages ~2R per win):
  EURUSD           : 56.7% | M15 ADX>=20 US session
  GBPUSD           : 53.1% | M15 ADX>=20 US session
  USDJPY           : 57.1% | M30 ADX>=20 London session
  Volatility 75    : 61.9% | M30 ADX>=25 US session
  BTCUSD           : 57.7% | M30 ADX>=20 London session
  USDCAD           : 66.7% | M30 ADX>=25 London+US session
  NZDCAD           : 63.6% | M15 ADX>=25 London session
  NZDJPY           : 64.3% | M30 ADX>=25 London session
  AUDUSD           : 60.9% | M30 ADX>=25 London+US session
  SOLUSD           : 60.7% | M15 ADX>=25 US session
  ADAUSD           : 60.9% | M15 ADX>=30 London session
  XTZUSD           : 62.5% | M30 ADX>=20 London session
  MLNUSD           : 65.0% | M15 ADX>=30 London session
  BATUSD           : 63.6% | M30 ADX>=30 London session
  AVAUSD           : 61.5% | H1  ADX>=30 24/7
  DOTUSD           : 60.6% | M15 ADX>=25 London session
  NERUSD           : 58.3% | M30 ADX>=20 24/7
  ETCUSD           : 58.6% | M15 ADX>=30 London session
  ETHUSD           : 57.1% | M15 ADX>=25 London session

All sessions in WAT (UTC+1).
MAX_OPEN_TRADES = 19 markets × 3 scaling orders = 57
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
            "adx_min":       25,
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
        "min_lot":      0.001,
        "atr_period":   14,
    },

    # ── BTCUSD ── 57.7% win rate | M30 | ADX>=20 | London session ───────────
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

    # ── USDCAD ── 66.7% win rate | M30 | ADX>=25 | London+US session ─────────
    "USDCAD": {
        "symbol":     "USDCAD",
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
                {"start": 8,  "end": 17},   # London session
                {"start": 15, "end": 23},   # US session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── NZDCAD ── 63.6% win rate | M15 | ADX>=25 | London session ────────────
    "NZDCAD": {
        "symbol":     "NZDCAD",
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
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── NZDJPY ── 64.3% win rate | M30 | ADX>=25 | London session ────────────
    "NZDJPY": {
        "symbol":     "NZDJPY",
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
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── AUDUSD ── 60.9% win rate | M30 | ADX>=25 | London+US session ─────────
    "AUDUSD": {
        "symbol":     "AUDUSD",
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
                {"start": 8,  "end": 17},   # London session
                {"start": 15, "end": 23},   # US session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.01,
        "atr_period":   14,
    },

    # ── SOLUSD ── 60.7% win rate | M15 | ADX>=25 | US session ───────────────
    "SOLUSD": {
        "symbol":     "SOLUSD",
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
                {"start": 15, "end": 23},   # US session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.5,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── XTZUSD ── 62.5% win rate | M30 | ADX>=20 | London session ────────────
    "XTZUSD": {
        "symbol":     "XTZUSD",
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
        "min_lot":      200.0,  # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── ADAUSD ── 60.9% win rate | M15 | ADX>=30 | London session ────────────
    "ADAUSD": {
        "symbol":     "ADAUSD",
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
            "sessions": [
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      200.0,  # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── MLNUSD ── 65.0% win rate | M15 | ADX>=30 | London session ────────────
    "MLNUSD": {
        "symbol":     "MLNUSD",
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
            "sessions": [
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      900.0,  # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── BATUSD ── 63.6% win rate | M30 | ADX>=30 | London session ────────────
    "BATUSD": {
        "symbol":     "BATUSD",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
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
            "sessions": [
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      600.0,  # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── AVAUSD ── 61.5% win rate | H1 | ADX>=30 | 24/7 ──────────────────────
    "AVAUSD": {
        "symbol":     "AVAUSD",
        "timeframe":  mt5.TIMEFRAME_H1,
        "tf_name":    "H1",
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
        "min_lot":      6.0,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── DOTUSD ── 60.6% win rate | M15 | ADX>=25 | London session ────────────
    "DOTUSD": {
        "symbol":     "DOTUSD",
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
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      40.0,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── NERUSD ── 58.3% win rate | M30 | ADX>=20 | 24/7 ─────────────────────
    "NERUSD": {
        "symbol":     "NERUSD",
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
            "sessions":      [],            # 24/7 — no session filter
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      50.0,   # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── ETCUSD ── 58.6% win rate | M15 | ADX>=30 | London session ────────────
    "ETCUSD": {
        "symbol":     "ETCUSD",
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
            "sessions": [
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      7.0,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },

    # ── ETHUSD ── 57.1% win rate | M15 | ADX>=25 | London session ────────────
    "ETHUSD": {
        "symbol":     "ETHUSD",
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
                {"start": 8, "end": 17},    # London session
            ]
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.1,    # Deriv actual minimum (verified from MT5)
        "atr_period":   14,
    },
}