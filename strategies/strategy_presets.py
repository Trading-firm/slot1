"""
strategies/strategy_presets.py
───────────────────────────────
10 named strategy variants for the trend_follower entry engine.

Each preset is a complete `entry` config dict (drop-in replacement for
markets.py "entry"). The strategy_sweep script iterates these per market
to find the best preset per pair.
"""

# Pattern bundles (re-used across presets)
ALL_PATTERNS  = ["hammer", "shooting_star", "bullish_engulfing", "bearish_engulfing"]
BULL_PATTERNS = ["hammer", "bullish_engulfing"]
BEAR_PATTERNS = ["shooting_star", "bearish_engulfing"]


def _base(**overrides) -> dict:
    """Default entry config; overrides selectively."""
    cfg = {
        "ema_trend":          200,
        "ema_pullback":       50,
        "pullback_lookback":  6,
        "chop_band_atr":      0.5,
        "min_rr":             2.0,
        "sl_buffer_atr":      0.3,
        "min_sl_atr":         0.3,
        "required_pattern":   ALL_PATTERNS,
        "sessions":           [[8, 22]],
        "max_sl_usd":         0,            # off in sweep — let pure A logic show
        "cooldown_bars":      0,
    }
    cfg.update(overrides)
    return cfg


STRATEGIES = {
    "baseline":     _base(),
    "rr_15":        _base(min_rr=1.5),
    "rr_30":        _base(min_rr=3.0),
    "bull_only":    _base(required_pattern=BULL_PATTERNS),
    "bear_only":    _base(required_pattern=BEAR_PATTERNS),
    "london":       _base(sessions=[[8, 13]]),
    "ny":           _base(sessions=[[13, 22]]),
    "overlap":      _base(sessions=[[13, 17]]),
    "fast_ema":     _base(ema_trend=100, ema_pullback=20, min_rr=1.5),
    "strict_trend": _base(chop_band_atr=1.5),
}