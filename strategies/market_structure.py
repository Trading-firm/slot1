"""
strategies/market_structure.py
───────────────────────────────
Phase 1: Market structure engine.

Reads a price dataframe and classifies what the market is doing:
  - UPTREND   = higher highs + higher lows
  - DOWNTREND = lower highs + lower lows
  - RANGE     = swings cluster in a tight band
  - CHOPPY    = no discernible pattern (default, safest)

Pure functions. No I/O, no MT5, no DB. Takes a DataFrame with columns
[Open, High, Low, Close] (index irrelevant), returns structure info.

Downstream modules (MTF, level memory, breakout entry) consume these.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
import pandas as pd


TREND_UP     = "UPTREND"
TREND_DOWN   = "DOWNTREND"
REGIME_RANGE = "RANGE"
REGIME_CHOP  = "CHOPPY"


@dataclass
class SwingPoint:
    idx:   int       # positional index into the dataframe
    price: float
    kind:  str       # "HIGH" or "LOW"


@dataclass
class StructureReport:
    trend:            str                  # TREND_UP / TREND_DOWN / REGIME_RANGE / REGIME_CHOP
    swings:           List[SwingPoint]     # chronological, confirmed only
    last_highs:       List[SwingPoint]     # up to `min_swings` most-recent swing highs
    last_lows:        List[SwingPoint]     # up to `min_swings` most-recent swing lows
    range_support:    Optional[float]      # set when trend == REGIME_RANGE
    range_resistance: Optional[float]      # set when trend == REGIME_RANGE
    reason:           str                  # human-readable explanation


def find_swing_points(df: pd.DataFrame, left: int = 5, right: int = 5) -> List[SwingPoint]:
    """
    Confirmed swings only. A bar at index i is a swing high if its high is
    strictly greater than every bar in [i-left, i-1] AND every bar in
    [i+1, i+right]. Same idea (minima) for swing lows.

    The last `right` bars of the frame can never yield confirmed swings.
    """
    n = len(df)
    if n < left + right + 1:
        return []

    highs = df["High"].values
    lows  = df["Low"].values
    out: List[SwingPoint] = []

    for i in range(left, n - right):
        h = highs[i]
        l = lows[i]
        # Swing high: strictly greater than both windows
        if h > highs[i-left:i].max() and h > highs[i+1:i+right+1].max():
            out.append(SwingPoint(idx=i, price=float(h), kind="HIGH"))
        # Swing low: strictly less than both windows
        if l < lows[i-left:i].min() and l < lows[i+1:i+right+1].min():
            out.append(SwingPoint(idx=i, price=float(l), kind="LOW"))
    return out


def _cluster_spread_pct(values: List[float]) -> float:
    """Range of a cluster as a percentage of its mean. 0 if <2 values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    return (max(values) - min(values)) / mean * 100.0


def classify_trend(
    df: pd.DataFrame,
    left:              int   = 5,
    right:             int   = 5,
    min_swings:        int   = 3,
    range_band_pct:    float = 2.0,   # highs/lows within this % of their mean = "clustered"
) -> StructureReport:
    """
    Walk chronological swings; decide regime.

    UPTREND   — last `min_swings` highs ascending AND last `min_swings` lows ascending
    DOWNTREND — last `min_swings` highs descending AND last `min_swings` lows descending
    RANGE     — highs cluster within `range_band_pct` AND lows cluster within `range_band_pct`
    CHOPPY    — nothing above holds (safest default)
    """
    swings = find_swing_points(df, left=left, right=right)
    highs  = [s for s in swings if s.kind == "HIGH"]
    lows   = [s for s in swings if s.kind == "LOW"]

    last_highs = highs[-min_swings:] if len(highs) >= min_swings else highs[:]
    last_lows  = lows[-min_swings:]  if len(lows)  >= min_swings else lows[:]

    if len(last_highs) < min_swings or len(last_lows) < min_swings:
        return StructureReport(
            trend=REGIME_CHOP, swings=swings,
            last_highs=last_highs, last_lows=last_lows,
            range_support=None, range_resistance=None,
            reason=f"Not enough swings yet ({len(highs)} highs, {len(lows)} lows, need {min_swings} of each)",
        )

    # Check ascending / descending patterns
    highs_prices = [s.price for s in last_highs]
    lows_prices  = [s.price for s in last_lows]

    highs_ascending  = all(a < b for a, b in zip(highs_prices, highs_prices[1:]))
    highs_descending = all(a > b for a, b in zip(highs_prices, highs_prices[1:]))
    lows_ascending   = all(a < b for a, b in zip(lows_prices, lows_prices[1:]))
    lows_descending  = all(a > b for a, b in zip(lows_prices, lows_prices[1:]))

    if highs_ascending and lows_ascending:
        return StructureReport(
            trend=TREND_UP, swings=swings,
            last_highs=last_highs, last_lows=last_lows,
            range_support=None, range_resistance=None,
            reason=f"{min_swings} HH + {min_swings} HL",
        )
    if highs_descending and lows_descending:
        return StructureReport(
            trend=TREND_DOWN, swings=swings,
            last_highs=last_highs, last_lows=last_lows,
            range_support=None, range_resistance=None,
            reason=f"{min_swings} LH + {min_swings} LL",
        )

    # Range — both clusters tight
    highs_spread = _cluster_spread_pct(highs_prices)
    lows_spread  = _cluster_spread_pct(lows_prices)
    if highs_spread <= range_band_pct and lows_spread <= range_band_pct:
        return StructureReport(
            trend=REGIME_RANGE, swings=swings,
            last_highs=last_highs, last_lows=last_lows,
            range_support=min(lows_prices),
            range_resistance=max(highs_prices),
            reason=f"Highs spread {highs_spread:.2f}% / lows spread {lows_spread:.2f}% (band {range_band_pct}%)",
        )

    return StructureReport(
        trend=REGIME_CHOP, swings=swings,
        last_highs=last_highs, last_lows=last_lows,
        range_support=None, range_resistance=None,
        reason=f"Mixed pattern (highs spread {highs_spread:.2f}%, lows spread {lows_spread:.2f}%)",
    )


def get_range_bounds(df: pd.DataFrame, **kwargs) -> Optional[Tuple[float, float]]:
    """Convenience: returns (support, resistance) if market is ranging, else None."""
    r = classify_trend(df, **kwargs)
    if r.trend == REGIME_RANGE:
        return (r.range_support, r.range_resistance)
    return None