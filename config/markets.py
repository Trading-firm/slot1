"""
config/markets.py
─────────────────
14 markets — selected by 90-day parameter sweep (scripts/backtest_sweep.py +
scripts/forex_candidate_sweep.py).
Strategy: Trend-Following — EMA20 pullback + ADX + RSI + optional HTF.
One trade per signal at 1:1 R:R. Break-even triggers at 0.5x ATR profit.

Selection criteria: expectancy * sqrt(trades), floor 0.3 trades/day.
XAUUSD was dropped (losing edge at all 72 tested configs — best was -0.02 exp).

Core 9 markets (90-day sweep, 1:1 R:R):
  Volatility 100 Index : 55.3% WR | 0.49 T/D | +0.11 exp | M30 ADX>=25 wide RSI HTF extended
  Crash 1000 Index     : 67.9% WR | 0.57 T/D | +0.36 exp | M15 ADX>=22 narrow RSI 24/7
  XAGUSD               : 73.5% WR | 0.22 T/D | +0.47 exp | H1  ADX>=18 wide RSI HTF loose 24/7
  Boom 1000 Index      : 60.3% WR | 0.73 T/D | +0.21 exp | M15 ADX>=18 narrow HTF loose 24/7
  XRPUSD               : 58.5% WR | 0.44 T/D | +0.17 exp | M15 ADX>=25 narrow London
  AUDJPY               : 58.5% WR | 0.30 T/D | +0.17 exp | M30 ADX>=25 wide RSI extended
  GBPJPY               : 61.1% WR | 0.54 T/D | +0.22 exp | M15 ADX>=22 narrow loose London
  EURJPY               : 54.5% WR | 0.40 T/D | +0.09 exp | M30 ADX>=18 wide RSI extended
  GBPCAD               : 63.4% WR | 0.76 T/D | +0.27 exp | M15 ADX>=25 narrow 24/7

New 5 Forex additions (ranked by edge score):
  EURNZD               : 74.2% WR | 0.22 T/D | +0.48 exp | M30 ADX>=22 narrow London
  USDCAD               : 62.1% WR | 1.01 T/D | +0.24 exp | M15 ADX>=18 narrow 24/7
  GBPAUD               : 72.4% WR | 0.22 T/D | +0.45 exp | M15 ADX>=25 narrow HTF London
  NZDCHF               : 61.8% WR | 0.77 T/D | +0.23 exp | M15 ADX>=18 narrow HTF 24/7
  NZDUSD               : 67.4% WR | 0.31 T/D | +0.35 exp | M30 ADX>=22 narrow HTF extended

Projected combined: ~7 trades/day avg, ~63% overall WR.
All sessions in WAT (UTC+1). Extended = 6-23 WAT (near-24h with wind-down).
MAX_OPEN_TRADES = 14 markets x 1 order = 14
"""
import MetaTrader5 as mt5

# Common RSI bands
RSI_NARROW = {"rsi_min_buy": 35, "rsi_max_buy": 58, "rsi_min_sell": 42, "rsi_max_sell": 65}
RSI_WIDE   = {"rsi_min_buy": 30, "rsi_max_buy": 65, "rsi_min_sell": 35, "rsi_max_sell": 70}

# Session presets (WAT)
SESS_LONDON    = [{"start": 8,  "end": 17}]
SESS_EXTENDED  = [{"start": 6,  "end": 23}]   # near-24h with wind-down
SESS_247       = []                            # empty = 24/7

MARKETS = {

    # ── Volatility 100 Index ── 55.3% WR | 0.49 T/D | +0.11 exp ─────────────
    "Volatility 100 Index": {
        "symbol":     "Volatility 100 Index",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         25,
            **RSI_WIDE,
            "pullback_tol":    0.0,
            "sessions":        SESS_EXTENDED,
            "htf_timeframe":   mt5.TIMEFRAME_H1,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      1.0,
        "atr_period":   14,
    },

    # ── Crash 1000 Index ── 67.9% WR | 0.57 T/D | +0.36 exp ─────────────────
    "Crash 1000 Index": {
        "symbol":     "Crash 1000 Index",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         22,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_247,
            # HTF off — Crash spikes are mean-reverting on H1, HTF hurt win rate
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.2,
        "atr_period":   14,
    },

    # ── XAGUSD ── 73.5% WR | 0.22 T/D | +0.47 exp ───────────────────────────
    "XAGUSD": {
        "symbol":     "XAGUSD",
        "timeframe":  mt5.TIMEFRAME_H1,
        "tf_name":    "H1",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         18,
            **RSI_WIDE,
            "pullback_tol":    0.3,   # loose: low within 0.3 ATR of EMA20
            "sessions":        SESS_247,
            "htf_timeframe":   mt5.TIMEFRAME_H1,   # H1 self-confirms on H4-equivalent EMAs
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── Boom 1000 Index ── 60.3% WR | 0.73 T/D | +0.21 exp ──────────────────
    "Boom 1000 Index": {
        "symbol":     "Boom 1000 Index",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         18,
            **RSI_NARROW,
            "pullback_tol":    0.3,
            "sessions":        SESS_247,
            "htf_timeframe":   mt5.TIMEFRAME_H1,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      1.0,
        "atr_period":   14,
    },

    # ── XRPUSD ── 58.5% WR | 0.44 T/D | +0.17 exp ───────────────────────────
    "XRPUSD": {
        "symbol":     "XRPUSD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         25,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_LONDON,
            # HTF off — crypto ignores traditional HTF trend structure
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      500.0,
        "atr_period":   14,
    },

    # ── AUDJPY ── 58.5% WR | 0.30 T/D | +0.17 exp ───────────────────────────
    "AUDJPY": {
        "symbol":     "AUDJPY",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         25,
            **RSI_WIDE,
            "pullback_tol":    0.0,
            "sessions":        SESS_EXTENDED,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── GBPJPY ── 61.1% WR | 0.54 T/D | +0.22 exp ───────────────────────────
    "GBPJPY": {
        "symbol":     "GBPJPY",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         22,
            **RSI_NARROW,
            "pullback_tol":    0.3,
            "sessions":        SESS_LONDON,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── EURJPY ── 54.5% WR | 0.40 T/D | +0.09 exp ───────────────────────────
    "EURJPY": {
        "symbol":     "EURJPY",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         18,
            **RSI_WIDE,
            "pullback_tol":    0.0,
            "sessions":        SESS_EXTENDED,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── GBPCAD ── 63.4% WR | 0.76 T/D | +0.27 exp ───────────────────────────
    "GBPCAD": {
        "symbol":     "GBPCAD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         25,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_247,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── EURNZD ── 74.2% WR | 0.22 T/D | +0.48 exp ───────────────────────────
    "EURNZD": {
        "symbol":     "EURNZD",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         22,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_LONDON,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── USDCAD ── 62.1% WR | 1.01 T/D | +0.24 exp ───────────────────────────
    "USDCAD": {
        "symbol":     "USDCAD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         18,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_247,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── GBPAUD ── 72.4% WR | 0.22 T/D | +0.45 exp ───────────────────────────
    "GBPAUD": {
        "symbol":     "GBPAUD",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         25,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_LONDON,
            "htf_timeframe":   mt5.TIMEFRAME_H1,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── NZDCHF ── 61.8% WR | 0.77 T/D | +0.23 exp ───────────────────────────
    "NZDCHF": {
        "symbol":     "NZDCHF",
        "timeframe":  mt5.TIMEFRAME_M15,
        "tf_name":    "M15",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         18,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_247,
            "htf_timeframe":   mt5.TIMEFRAME_H1,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },

    # ── NZDUSD ── 67.4% WR | 0.31 T/D | +0.35 exp ───────────────────────────
    "NZDUSD": {
        "symbol":     "NZDUSD",
        "timeframe":  mt5.TIMEFRAME_M30,
        "tf_name":    "M30",
        "strategy":   "trend_following",
        "filters": {
            "ema_fast":        20,
            "ema_slow":        50,
            "ema_trend":       200,
            "adx_period":      14,
            "adx_min":         22,
            **RSI_NARROW,
            "pullback_tol":    0.0,
            "sessions":        SESS_EXTENDED,
            "htf_timeframe":   mt5.TIMEFRAME_H1,
        },
        "max_sl_atr":   2.5,
        "swing_window": 10,
        "min_lot":      0.06,
        "atr_period":   14,
    },
}
