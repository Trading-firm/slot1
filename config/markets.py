"""
config/markets.py
─────────────────
Structure-based trader on BTCUSD.

Strategy 'structure_trader' pipeline:
  1. MTF bias — H4 leads, H1 vetoes conflicts (NEVER against bigger TF trend)
  2. Level memory — swings + range bounds persisted to data/levels.db
  3. Entry engine — pure price action, high-WR focus (see scenario priority below)
  4. Dual-trade execution (A + optional B scalp)
  5. Structural cooldown — no re-entry until a new confirmed M15 swing forms after last exit

── Scenario priority (highest WR first) ──────────────────────────────────────
  1. sweep_reclaim  — price wicks past a swing level then closes back through it
                      (stop-hunt reversal — crypto's highest-WR pattern)
  2. level_touch    — bar tests swing level, closes strongly back (proven S/R only,
                      requires prior touches + strong close)
  3. range_reversal — M15 swing at H4 range bound
  4. range_breakout / trend_pullback — off by default (historically net-negative)

── Session filter ────────────────────────────────────────────────────────────
  sessions = [[8, 22]] → trade 08:00-22:00 UTC only (London + NY)
  Outside session = no entries (Asian hours = chop on BTC M15).

Editable per market:
  dual_trade.trade_a_lot / trade_b_lot     lot sizes
  dual_trade.trade_b_profit_usd            B's scalp target in $  (0 = disable B)
  dual_trade.trade_b_max_loss_usd          B's max loss cap
  entry.min_rr                             R:R target for A
  entry.min_prior_touches                  require N prior touches of a level before trading it
  entry.min_body_ratio                     close must be in top/bottom (1-min_body_ratio) of bar
  entry.sessions                           list of [start,end] UTC hour pairs
  entry.max_sl_usd                         reject setups exceeding this A-loss cap
  entry.min_sl_atr                         floor SL at this × ATR  (0 = off)
"""
import MetaTrader5 as mt5

MARKETS = {

    # ── BTCUSD — Structure-based trader ─────────────────────────────────────
    # symbol_candidates: bot picks the first one that exists on the connected
    # account. Demo (Trial) uses 'BTCUSD'; real micro account uses 'BTCUSDm'.
    # Add more variants here if other brokers/account types use different names.
    "BTCUSD": {
        "symbol_candidates": ["BTCUSD", "BTCUSDm", "BTCUSDc", "BTC/USD"],
        "symbol":    "BTCUSD",   # fallback / legacy display name
        "timeframe": mt5.TIMEFRAME_M15,
        "tf_name":   "M15",
        "strategy":  "structure_trader",

        # Dual-trade execution — places 2 orders per signal (A + B)
        "dual_trade": {
            "trade_a_lot":            0.01,
            "trade_b_lot":            0.01,
            "trade_b_profit_usd":     1,    # $2 scalp (0 = disable trade B entirely)
            "trade_b_max_loss_usd":  0,    # tighter SL — B's avg loss must be < avg win
            "min_balance_for_b":      100.0,   # accounts below this skip B (capital protection)
        },

        # Entry engine thresholds
        "entry": {
            "min_rr":               1.0,      # 1R targets reach far more often than 1.5R+ on M15
            "min_sl_atr":           0.5,      # floor SL at ½ ATR — kills micro-SL trades that spread eats
            "max_sl_usd":           15.0,
            "near_bound_atr":       1.5,
            "swing_near_bound_atr": 2.5,
            "max_lookback_bars":    30,
            "breakout_lookback_min":30,
            "tp_b_profit_usd":      2.00,
            # Session filter — London + NY only (skip Asian chop 22-08 UTC)
            "sessions":             [[8, 22]],
            # Scenario kill-switches
            "enable_sweep_reclaim":   True,   # primary high-WR scenario
            "enable_level_touch":     True,   # secondary
            "enable_range_reversal":  False,
            "enable_range_breakout":  False,
            "enable_trend_pullback":  False,
            # Quality filters
            "min_prior_touches":     2,       # level must have been tested ≥2x before entry
            "min_body_ratio":        0.4,     # close in top/bottom 40% of bar range (strong rejection)
            "sl_buffer_atr_sweep":   0.2,     # SL placed 0.2 ATR beyond sweep wick
            "min_sweep_atr":         0.1,     # wick must pierce level by ≥ 0.1 ATR
        },

        # Structure detection thresholds
        "structure": {
            "h4_range_band_pct":    4.0,    # BTC ranges are wider — 4% band for H4
            "h1_range_band_pct":    2.5,
            "m15_range_band_pct":   2.0,
            "swing_left":           5,
            "swing_right":          5,
            "min_swings":           3,
            "h4_bars":              400,
            "h1_bars":              500,
            "m15_bars":             500,
        },
    },
}