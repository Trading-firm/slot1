"""
strategies/mtf_analysis.py
───────────────────────────
Phase 2: Multi-Timeframe analyzer.

Job: decide the BIAS (BUY / SELL / RANGE / NEUTRAL).

Rules:
  - H4 is the boss. Its trend dictates the bias.
  - H1 is a vetoer. If H1 strongly disagrees with H4, bias goes NEUTRAL.
  - M15 is context — it matters for ENTRY (Phase 4), not bias.
  - RANGE is a tradable bias: Phase 4 uses it to trade reversals at
    support/resistance AND breakouts when the range snaps.
  - CHOPPY = no tradable structure at all.

What this module does NOT do:
  - Does not fetch data. Caller supplies DataFrames.
  - Does not decide entries.
  - Does not know about open trades / cooldowns.
"""
from dataclasses import dataclass
from typing import Optional, Tuple
import pandas as pd

from strategies.market_structure import (
    classify_trend, StructureReport,
    TREND_UP, TREND_DOWN, REGIME_RANGE, REGIME_CHOP,
)


BIAS_BUY     = "BUY"       # only BUY entries allowed (H4 uptrend)
BIAS_SELL    = "SELL"      # only SELL entries allowed (H4 downtrend)
BIAS_RANGE   = "RANGE"     # range trading: reversals at bounds + breakout trades
BIAS_NEUTRAL = "NEUTRAL"   # no tradable structure — stay flat


@dataclass
class MTFReport:
    bias:         str               # BIAS_BUY / BIAS_SELL / BIAS_RANGE / BIAS_NEUTRAL
    h4_struct:    StructureReport
    h1_struct:    StructureReport
    m15_struct:   StructureReport
    reason:       str               # human-readable
    range_bounds: Optional[Tuple[float, float]] = None   # (support, resistance) when bias == RANGE


def analyze_mtf(
    df_h4:  pd.DataFrame,
    df_h1:  pd.DataFrame,
    df_m15: pd.DataFrame,
    left:             int   = 5,
    right:            int   = 5,
    min_swings:       int   = 3,
    range_band_pct:   float = 2.0,
    h4_range_band:    float = 3.0,   # H4 band loosened — moves are bigger at 4-hour scale
) -> MTFReport:
    """
    Decides bias from H4, vetoed by H1 on trend conflicts.

    Bias logic:
      H4 UPTREND    → BUY   (unless H1 DOWNTREND, then NEUTRAL)
      H4 DOWNTREND  → SELL  (unless H1 UPTREND,   then NEUTRAL)
      H4 RANGE      → RANGE — Phase 4 trades reversals at support/resistance AND
                              catches breakouts when price leaves the range.
                              Skipped if H1 is strongly trending against the range
                              (means range is about to break on H1, wait for clarity).
      H4 CHOPPY     → NEUTRAL — no tradable structure, stay flat.
    """
    h4  = classify_trend(df_h4,  left=left, right=right, min_swings=min_swings, range_band_pct=h4_range_band)
    h1  = classify_trend(df_h1,  left=left, right=right, min_swings=min_swings, range_band_pct=range_band_pct)
    m15 = classify_trend(df_m15, left=left, right=right, min_swings=min_swings, range_band_pct=range_band_pct)

    # H4 CHOPPY — no structure, stay out entirely.
    if h4.trend == REGIME_CHOP:
        return MTFReport(
            bias=BIAS_NEUTRAL, h4_struct=h4, h1_struct=h1, m15_struct=m15,
            reason="H4 CHOPPY — no tradable structure, stay flat.",
        )

    # H4 RANGE — tradable as range: Phase 4 will trade reversals + breakouts.
    if h4.trend == REGIME_RANGE:
        bounds = (h4.range_support, h4.range_resistance)
        return MTFReport(
            bias=BIAS_RANGE, h4_struct=h4, h1_struct=h1, m15_struct=m15,
            range_bounds=bounds,
            reason=(
                f"H4 RANGE ${bounds[0]:.2f}-${bounds[1]:.2f} — "
                f"look for reversals at bounds OR breakout when price closes outside range."
            ),
        )

    # H4 UPTREND — BUY bias unless H1 strongly disagrees
    if h4.trend == TREND_UP:
        if h1.trend == TREND_DOWN:
            return MTFReport(
                bias=BIAS_NEUTRAL, h4_struct=h4, h1_struct=h1, m15_struct=m15,
                reason="H4 UPTREND but H1 DOWNTREND — conflict, stay flat.",
            )
        return MTFReport(
            bias=BIAS_BUY, h4_struct=h4, h1_struct=h1, m15_struct=m15,
            reason=f"H4 UPTREND (H1 {h1.trend}) — wait for BUY entries on M15 pullback + confirmation.",
        )

    # H4 DOWNTREND — SELL bias unless H1 strongly disagrees
    if h1.trend == TREND_UP:
        return MTFReport(
            bias=BIAS_NEUTRAL, h4_struct=h4, h1_struct=h1, m15_struct=m15,
            reason="H4 DOWNTREND but H1 UPTREND — conflict, stay flat.",
        )
    return MTFReport(
        bias=BIAS_SELL, h4_struct=h4, h1_struct=h1, m15_struct=m15,
        reason=f"H4 DOWNTREND (H1 {h1.trend}) — wait for SELL entries on M15 pullback + confirmation.",
    )