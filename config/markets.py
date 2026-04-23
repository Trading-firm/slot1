"""
config/markets.py
─────────────────
Structure-based trader on BTCUSD.

Strategy 'structure_trader' pipeline:
  1. MTF bias — H4 leads, H1 vetoes conflicts (NEVER against bigger TF trend)
  2. Level memory — swings + range bounds persisted to data/levels.db
  3. Entry engine — pure price action (no candlestick body checks):
       • trend_pullback — H4 trending + M15 new higher/lower swing formed
       • range_reversal — H4 ranging + M15 higher/lower swing AT a bound
       • range_breakout — price CLOSED beyond H4 range bound
  4. Dual-trade execution:
       • struct_A (main) — 1:2 R:R target (capped at structural levels if closer)
                           Active M15 structure-break monitor closes early on invalidation
       • struct_B ($2 scalp) — TIGHTER SL (max $5 loss), closes at +$2 P/L
       • When B hits target, A's SL moves to breakeven
  5. Structural cooldown — no re-entry until a new confirmed M15 swing forms after last exit

BTC note: wider M15 ATR (~$270 vs gold's $12) means structural SLs are naturally
wider in price terms but similar in $ terms at 0.01 lot. Spread $6 is much wider than
gold's $0.15 — not a scalper concern at M15 structure timing.

Editable per market:
  dual_trade.trade_a_lot / trade_b_lot     lot sizes
  dual_trade.trade_b_profit_usd            scalp target in $  (0 = disable B)
  dual_trade.trade_b_max_loss_usd          Trade B's max loss cap
  entry.min_rr                             R:R target for A (default 2.0)
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
            "trade_b_profit_usd":     0,    # $2 scalp (0 = disable trade B entirely)
            "trade_b_max_loss_usd":  0,    # tighter SL — B's avg loss must be < avg win
            "min_balance_for_b":      100.0,   # accounts below this skip B (capital protection)
        },

        # Entry engine thresholds
        "entry": {
            "min_rr":               2.0,
            "min_sl_atr":           0.3,
            "max_sl_usd":           15.0,
            "near_bound_atr":       1.5,
            "swing_near_bound_atr": 2.5,
            "max_lookback_bars":    30,
            "breakout_lookback_min":30,
            "tp_b_profit_usd":      2.00,
            # Scenario kill-switches (backtest showed these as net-negative)
            "enable_trend_pullback":  False,
            "enable_range_breakout":  False,
            "enable_range_reversal":  True,
            "enable_level_touch":     True,
            # Quality filter: only trade levels that have been tested at least N times
            # before our entry attempt (proven S/R, not random new dips/rallies).
            "min_prior_touches":     1,
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