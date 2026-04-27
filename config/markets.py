"""
config/markets.py
─────────────────
Trend-following trader across 15 forex pairs.

Each market has its own `entry` config — typically one of the 10 named
strategy presets in strategies/strategy_presets.py, chosen per market
based on backtest performance (strategy_sweep.py).

Strategy 'trend_follower' pipeline (per "The Candlestick Trading Bible"):
  1. Trend filter: M15 close vs EMA200 (with chop-zone band)
  2. Pullback: price retraced into EMA50 area within last N bars
  3. Entry confirmation: directional candlestick pattern fires on entry bar
  4. Single trade A (Trade B disabled across all markets)
  5. Trend-flip early exit: close if M15 close crosses EMA200 against the trade
"""
import MetaTrader5 as mt5
from strategies.strategy_presets import STRATEGIES


def _fx_market(name: str, candidates, strategy_preset: str = "baseline",
               max_sl_usd: float = 3.0) -> dict:
    """
    Build a market config. `strategy_preset` selects an entry config from
    strategies/strategy_presets.py (one of: baseline, rr_15, rr_30, bull_only,
    bear_only, london, ny, overlap, fast_ema, strict_trend).
    """
    entry = dict(STRATEGIES[strategy_preset])     # copy preset
    entry["max_sl_usd"] = max_sl_usd              # apply per-market SL cap
    return {
        "symbol_candidates": candidates,
        "symbol":    name,
        "timeframe": mt5.TIMEFRAME_M15,
        "tf_name":   "M15",
        "strategy":  "trend_follower",
        "strategy_preset": strategy_preset,
        "dual_trade": {
            "trade_a_lot":           0.01,
            "trade_b_lot":           0.01,
            "trade_b_profit_usd":    0,        # Trade B disabled across all markets
            "trade_b_max_loss_usd":  0,
            "min_balance_for_b":     100.0,
        },
        "entry": entry,
    }


MARKETS = {
    # ── 9 reliable winners — locked to their best-performing strategy ──────
    # (sweep over 10 strategies × 30-day backtest, 2026-03-22 → 2026-04-22)
    # Exotic pairs (USDSEK/NOK/MXN/ZAR) removed: foreign-currency P/L produced
    # inflated backtest numbers; real account P/L would need conversion.
    "GBPUSD": _fx_market("GBPUSD", ["GBPUSD", "GBPUSDm", "GBPUSDc"],
                         strategy_preset="baseline",   max_sl_usd=4.0),
    "USDCAD": _fx_market("USDCAD", ["USDCAD", "USDCADm", "USDCADc"],
                         strategy_preset="rr_15",      max_sl_usd=3.5),
    "GBPJPY": _fx_market("GBPJPY", ["GBPJPY", "GBPJPYm", "GBPJPYc"],
                         strategy_preset="rr_30",      max_sl_usd=6.0),
    "EURUSD": _fx_market("EURUSD", ["EURUSD", "EURUSDm", "EURUSDc"],
                         strategy_preset="bull_only",  max_sl_usd=3.0),
    "EURCAD": _fx_market("EURCAD", ["EURCAD", "EURCADm", "EURCADc"],
                         strategy_preset="london",     max_sl_usd=4.0),
    "GBPAUD": _fx_market("GBPAUD", ["GBPAUD", "GBPAUDm", "GBPAUDc"],
                         strategy_preset="overlap",    max_sl_usd=5.0),
    "USDSGD": _fx_market("USDSGD", ["USDSGD", "USDSGDm", "USDSGDc"],
                         strategy_preset="overlap",    max_sl_usd=3.0),
    "AUDCAD": _fx_market("AUDCAD", ["AUDCAD", "AUDCADm", "AUDCADc"],
                         strategy_preset="overlap",    max_sl_usd=3.5),
    "GBPSGD": _fx_market("GBPSGD", ["GBPSGD", "GBPSGDm", "GBPSGDc"],
                         strategy_preset="ny",         max_sl_usd=5.0),
}