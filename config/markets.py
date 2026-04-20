"""
config/markets.py
─────────────────
Momentum candle scalper on Exness — XAUUSD + BTCUSD.

Winning configs from 90-day sweeps with spread modeled:

  XAUUSD (gold) — scripts/gold_scalper_sweep.py
    M15 | body >= 0.75 | R:R = 1:1.5 | EMA8 filter ON | min_range >= 25*spread | 24/5
    WR 43.3%, ~3 T/D, +0.07R exp, +$1,036/90d @ 0.01 lot (spread $0.155)
    (Tightened from 1:2.5 for more frequent smaller wins per user preference)

  BTCUSD — scripts/btc_scalper_sweep.py + btc_fixed_target_backtest.py
    M15 | body >= 0.75 | R:R = 1:1.0 | EMA8 filter OFF | min_range >= 5*spread | 24/7
    WR 54.9%, ~6 T/D, +$306.80/90d @ 0.01 lot (spread $6.00)
    (Tightened from 1:1.5 — user wants more frequent wins; 1:1.0 keeps the math honest)

Combined projection: ~6.8 T/D, ~45% WR, ~$1,893/90d @ 0.01 lot per market.

Strategy type: momentum candle trigger.
  - Strong-bodied candle (body >= body_min_pct of range, larger than avg of prior 5)
  - Close in the upper/lower 1/3 of the range (direction confirmed)
  - Range >= min_range_x_spread × spread (skip small bars)
  - Optional EMA8 alignment (per market)
  - Structural SL: prior candle low/high -/+ 0.1*ATR buffer
  - TP: SL_distance × rr_ratio

Entry: next bar open (market order).
Close: SL or TP broker-side. No trailing, no early exit.
"""
import MetaTrader5 as mt5

MARKETS = {

    # ── XAUUSD (Gold) — Momentum Candle Scalper ─────────────────────────────
    "XAUUSD": {
        "symbol":    "XAUUSD",
        "timeframe": mt5.TIMEFRAME_M15,
        "tf_name":   "M15",
        "strategy":  "scalper",
        "filters": {
            "body_min_pct":       0.75,   # candle body >= 75% of range
            "body_lookback":      5,
            "close_extremity":    1/3,    # close in upper/lower 1/3
            "min_range_x_spread": 25,     # range >= 25x spread (skip small candles)
            "use_ema_filter":     True,
            "ema_period":         8,
            "sl_buffer_atr":      0.1,    # SL = candle low/high +/- 0.1*ATR
            "rr_ratio":           1.5,    # TP = SL_dist * 1.5 (backtest winner)
            # Fixed $ profit target removed — verified via backtest it LOSES money
            # (avg SL $19 >> $5.60 TP means 65% WR still net negative).
            "atr_period":         14,
            "sessions":           [],     # 24/5 (gold closed weekends anyway)
        },
        "min_lot":      0.01,   # Exness min; $1 per $1 move
        "atr_period":   14,
        "swing_window": 10,     # unused by scalper but kept for compatibility
    },

    # ── BTCUSD — Momentum Candle Scalper ────────────────────────────────────
    "BTCUSD": {
        "symbol":    "BTCUSD",
        "timeframe": mt5.TIMEFRAME_M15,
        "tf_name":   "M15",
        "strategy":  "scalper",
        "filters": {
            "body_min_pct":       0.75,
            "body_lookback":      5,
            "close_extremity":    1/3,
            "min_range_x_spread": 5,      # tighter than gold — BTC ranges are huge
            "use_ema_filter":     False,  # EMA filter reduced profit on BTC
            "ema_period":         8,
            "sl_buffer_atr":      0.1,
            "rr_ratio":           1.0,    # 54.9% WR, 6 T/D, +$306.80/90d (backtest)
            "atr_period":         14,
            "sessions":           [],     # 24/7
        },
        "min_lot":      0.05,   # Exness min; $1 price move = $0.01 P/L
        "atr_period":   14,
        "swing_window": 10,
    },
}