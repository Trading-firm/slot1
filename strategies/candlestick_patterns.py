"""
strategies/candlestick_patterns.py
───────────────────────────────────
Named candlestick pattern detectors from "The Candlestick Trading Bible".

Pure functions. Each detector inspects a closed bar (default = last closed,
index -2) and returns a PatternMatch or None. No I/O, no MT5.

Patterns implemented:
  Single-candle  : pin_bar (hammer / shooting_star), doji, dragonfly_doji,
                   gravestone_doji
  Two-candle     : engulfing (bull/bear), inside_bar (harami),
                   tweezers_top, tweezers_bottom
  Three-candle   : morning_star, evening_star

Direction returned by the detector is the SIGNAL DIRECTION for trading
("BUY" = long, "SELL" = short). The book's rule is to take the signal
ONLY when it aligns with higher-timeframe trend — that gating is the
caller's job (entry_engine already does it).

Run `python strategies/candlestick_patterns.py` to execute self-tests.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import pandas as pd


DIR_BUY  = "BUY"
DIR_SELL = "SELL"


@dataclass
class PatternMatch:
    name:      str
    direction: str                            # DIR_BUY or DIR_SELL
    bar_idx:   int                            # positional index into the df
    details:   Dict[str, Any] = field(default_factory=dict)


def _ohlc(df: pd.DataFrame, idx: int):
    return (
        float(df["Open"].iloc[idx]),
        float(df["High"].iloc[idx]),
        float(df["Low"].iloc[idx]),
        float(df["Close"].iloc[idx]),
    )


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, l: float) -> float:
    return h - l


def _upper_shadow(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_shadow(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def _is_bullish(o: float, c: float) -> bool:
    return c > o


def _is_bearish(o: float, c: float) -> bool:
    return c < o


# ── Single-candle patterns ────────────────────────────────────────────────────


def detect_pin_bar(
    df: pd.DataFrame,
    bar_idx:           int   = -2,
    body_max_ratio:    float = 0.33,    # body ≤ 1/3 of bar range
    shadow_min_ratio:  float = 2.0,     # signal shadow ≥ 2× body (book's rule)
    opp_shadow_max:    float = 0.33,    # opposite shadow ≤ 1/3 of bar range
) -> Optional[PatternMatch]:
    """
    Pin bar (hammer / shooting star). The book treats them as the same shape;
    the direction is determined by which side has the long shadow:
      - long lower shadow → BUY  (hammer)
      - long upper shadow → SELL (shooting star)
    """
    o, h, l, c = _ohlc(df, bar_idx)
    rng = _range(h, l)
    if rng <= 0:
        return None

    body  = _body(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)

    if body > body_max_ratio * rng:
        return None

    # Hammer: long lower, short upper
    if (body > 0 and lower >= shadow_min_ratio * body
        and upper <= opp_shadow_max * rng):
        return PatternMatch(
            name="hammer", direction=DIR_BUY, bar_idx=bar_idx,
            details={"body": body, "lower": lower, "upper": upper, "range": rng},
        )

    # Shooting star: long upper, short lower
    if (body > 0 and upper >= shadow_min_ratio * body
        and lower <= opp_shadow_max * rng):
        return PatternMatch(
            name="shooting_star", direction=DIR_SELL, bar_idx=bar_idx,
            details={"body": body, "upper": upper, "lower": lower, "range": rng},
        )

    return None


def detect_doji(
    df: pd.DataFrame,
    bar_idx:        int   = -2,
    max_body_ratio: float = 0.05,    # body ≤ 5% of range = "open ≈ close"
) -> Optional[PatternMatch]:
    """
    Doji = open ≈ close. Indicates indecision. Direction is None — the book
    treats doji as a context-dependent reversal warning, not a directional
    signal on its own. We return DIR_BUY for callers that just want "any
    reversal hint at support" usage, but most callers should prefer
    dragonfly/gravestone variants which carry direction.

    For pure indecision detection without a direction, callers should check
    `pattern.name == "doji"` and ignore `pattern.direction`.
    """
    o, h, l, c = _ohlc(df, bar_idx)
    rng = _range(h, l)
    if rng <= 0:
        return None
    body = _body(o, c)
    if body > max_body_ratio * rng:
        return None

    return PatternMatch(
        name="doji", direction=DIR_BUY, bar_idx=bar_idx,
        details={"body": body, "range": rng, "ratio": body / rng if rng else 0},
    )


def detect_dragonfly_doji(
    df: pd.DataFrame,
    bar_idx:           int   = -2,
    max_body_ratio:    float = 0.05,
    max_upper_ratio:   float = 0.10,    # tiny upper shadow
    min_lower_ratio:   float = 0.60,    # long lower shadow ≥ 60% of range
) -> Optional[PatternMatch]:
    """Dragonfly Doji — bullish reversal. Open ≈ high ≈ close, long lower tail."""
    o, h, l, c = _ohlc(df, bar_idx)
    rng = _range(h, l)
    if rng <= 0:
        return None
    body  = _body(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)

    if (body <= max_body_ratio * rng
        and upper <= max_upper_ratio * rng
        and lower >= min_lower_ratio * rng):
        return PatternMatch(
            name="dragonfly_doji", direction=DIR_BUY, bar_idx=bar_idx,
            details={"body": body, "upper": upper, "lower": lower, "range": rng},
        )
    return None


def detect_gravestone_doji(
    df: pd.DataFrame,
    bar_idx:           int   = -2,
    max_body_ratio:    float = 0.05,
    max_lower_ratio:   float = 0.10,
    min_upper_ratio:   float = 0.60,
) -> Optional[PatternMatch]:
    """Gravestone Doji — bearish reversal. Open ≈ low ≈ close, long upper tail."""
    o, h, l, c = _ohlc(df, bar_idx)
    rng = _range(h, l)
    if rng <= 0:
        return None
    body  = _body(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)

    if (body <= max_body_ratio * rng
        and lower <= max_lower_ratio * rng
        and upper >= min_upper_ratio * rng):
        return PatternMatch(
            name="gravestone_doji", direction=DIR_SELL, bar_idx=bar_idx,
            details={"body": body, "upper": upper, "lower": lower, "range": rng},
        )
    return None


# ── Two-candle patterns ───────────────────────────────────────────────────────


def _has_prior(df: pd.DataFrame, bar_idx: int, n: int) -> bool:
    """True if df has at least n bars before bar_idx (so bar_idx-n is valid)."""
    if bar_idx >= 0:
        return bar_idx >= n
    return len(df) + bar_idx >= n


def detect_engulfing(
    df: pd.DataFrame,
    bar_idx: int = -2,
) -> Optional[PatternMatch]:
    """
    Engulfing bar. Second candle's body fully covers prior candle's body, AND
    the two candles are opposite colors (bullish engulfing red, or bearish
    engulfing green). Color matters here — same-color engulfing is just a
    big-body continuation, not the textbook reversal pattern.
    """
    if not _has_prior(df, bar_idx, 1):
        return None
    o1, h1, l1, c1 = _ohlc(df, bar_idx - 1)
    o2, h2, l2, c2 = _ohlc(df, bar_idx)

    body1_top    = max(o1, c1)
    body1_bottom = min(o1, c1)
    body2_top    = max(o2, c2)
    body2_bottom = min(o2, c2)

    engulfs = body2_top >= body1_top and body2_bottom <= body1_bottom

    if not engulfs:
        return None
    # Don't fire if the prior candle has effectively no body (degenerate)
    if (body1_top - body1_bottom) <= 0:
        return None

    if _is_bearish(o1, c1) and _is_bullish(o2, c2):
        return PatternMatch(
            name="bullish_engulfing", direction=DIR_BUY, bar_idx=bar_idx,
            details={"body1": body1_top - body1_bottom, "body2": body2_top - body2_bottom},
        )
    if _is_bullish(o1, c1) and _is_bearish(o2, c2):
        return PatternMatch(
            name="bearish_engulfing", direction=DIR_SELL, bar_idx=bar_idx,
            details={"body1": body1_top - body1_bottom, "body2": body2_top - body2_bottom},
        )
    return None


def detect_inside_bar(
    df: pd.DataFrame,
    bar_idx: int = -2,
) -> Optional[PatternMatch]:
    """
    Inside bar (Harami). Second bar's HIGH/LOW range sits inside first bar's
    HIGH/LOW range. Direction is None on its own — the book uses inside bars
    as a CONTEXTUAL signal:
      - in an uptrend → continuation (BUY on break of mother bar high)
      - in a downtrend → continuation (SELL on break of mother bar low)
      - at the top/bottom of a trend → reversal
    Caller decides direction from MTF context. We return the pattern with
    direction=None encoded as a separate flag in details.
    """
    if not _has_prior(df, bar_idx, 1):
        return None
    _, h1, l1, _ = _ohlc(df, bar_idx - 1)
    _, h2, l2, _ = _ohlc(df, bar_idx)

    if h2 <= h1 and l2 >= l1 and (h1 - l1) > 0 and (h2 - l2) < (h1 - l1):
        # Direction is contextual; stamp BUY as a placeholder and let caller
        # apply MTF direction. Details carry mother-bar levels for breakout SL/TP.
        return PatternMatch(
            name="inside_bar", direction=DIR_BUY, bar_idx=bar_idx,
            details={
                "mother_high":   h1,
                "mother_low":    l1,
                "mother_range":  h1 - l1,
                "baby_range":    h2 - l2,
                "directional":   False,   # caller must supply direction from context
            },
        )
    return None


def detect_tweezers_top(
    df: pd.DataFrame,
    bar_idx:    int   = -2,
    high_tol:   float = 0.0001,    # allow tiny equality tolerance
) -> Optional[PatternMatch]:
    """
    Tweezers top — bearish reversal. First bar bullish, second bar bearish,
    both with matching highs.
    """
    if not _has_prior(df, bar_idx, 1):
        return None
    o1, h1, l1, c1 = _ohlc(df, bar_idx - 1)
    o2, h2, l2, c2 = _ohlc(df, bar_idx)

    if (_is_bullish(o1, c1) and _is_bearish(o2, c2)
        and abs(h1 - h2) <= high_tol * max(h1, h2)):
        return PatternMatch(
            name="tweezers_top", direction=DIR_SELL, bar_idx=bar_idx,
            details={"high1": h1, "high2": h2},
        )
    return None


def detect_tweezers_bottom(
    df: pd.DataFrame,
    bar_idx:    int   = -2,
    low_tol:    float = 0.0001,
) -> Optional[PatternMatch]:
    """
    Tweezers bottom — bullish reversal. First bar bearish, second bar bullish,
    both with matching lows.
    """
    if not _has_prior(df, bar_idx, 1):
        return None
    o1, h1, l1, c1 = _ohlc(df, bar_idx - 1)
    o2, h2, l2, c2 = _ohlc(df, bar_idx)

    if (_is_bearish(o1, c1) and _is_bullish(o2, c2)
        and abs(l1 - l2) <= low_tol * max(l1, l2)):
        return PatternMatch(
            name="tweezers_bottom", direction=DIR_BUY, bar_idx=bar_idx,
            details={"low1": l1, "low2": l2},
        )
    return None


# ── Three-candle patterns ─────────────────────────────────────────────────────


def detect_morning_star(
    df: pd.DataFrame,
    bar_idx:           int   = -2,
    star_max_body_pct: float = 0.5,    # middle candle's body ≤ 50% of first's body
) -> Optional[PatternMatch]:
    """
    Morning star — bullish reversal. Three candles:
      1. Large bearish
      2. Small body (any color or doji)
      3. Bullish that closes ABOVE the midpoint of candle 1's body (book's rule)
    """
    if not _has_prior(df, bar_idx, 2):
        return None
    o1, h1, l1, c1 = _ohlc(df, bar_idx - 2)
    o2, h2, l2, c2 = _ohlc(df, bar_idx - 1)
    o3, h3, l3, c3 = _ohlc(df, bar_idx)

    body1 = _body(o1, c1)
    body2 = _body(o2, c2)
    if body1 <= 0:
        return None
    if not _is_bearish(o1, c1):
        return None
    if not _is_bullish(o3, c3):
        return None
    if body2 > star_max_body_pct * body1:
        return None
    midpoint1 = (o1 + c1) / 2.0
    if c3 <= midpoint1:
        return None

    return PatternMatch(
        name="morning_star", direction=DIR_BUY, bar_idx=bar_idx,
        details={"body1": body1, "body2": body2, "midpoint1": midpoint1, "close3": c3},
    )


def detect_evening_star(
    df: pd.DataFrame,
    bar_idx:           int   = -2,
    star_max_body_pct: float = 0.5,
) -> Optional[PatternMatch]:
    """
    Evening star — bearish reversal. Mirror of morning star.
      1. Large bullish
      2. Small body
      3. Bearish that closes BELOW the midpoint of candle 1's body
    """
    if not _has_prior(df, bar_idx, 2):
        return None
    o1, h1, l1, c1 = _ohlc(df, bar_idx - 2)
    o2, h2, l2, c2 = _ohlc(df, bar_idx - 1)
    o3, h3, l3, c3 = _ohlc(df, bar_idx)

    body1 = _body(o1, c1)
    body2 = _body(o2, c2)
    if body1 <= 0:
        return None
    if not _is_bullish(o1, c1):
        return None
    if not _is_bearish(o3, c3):
        return None
    if body2 > star_max_body_pct * body1:
        return None
    midpoint1 = (o1 + c1) / 2.0
    if c3 >= midpoint1:
        return None

    return PatternMatch(
        name="evening_star", direction=DIR_SELL, bar_idx=bar_idx,
        details={"body1": body1, "body2": body2, "midpoint1": midpoint1, "close3": c3},
    )


# ── Orchestrator ──────────────────────────────────────────────────────────────


ALL_DETECTORS = [
    detect_pin_bar,
    detect_dragonfly_doji,
    detect_gravestone_doji,
    detect_engulfing,
    detect_tweezers_top,
    detect_tweezers_bottom,
    detect_morning_star,
    detect_evening_star,
    detect_inside_bar,
    detect_doji,            # last — most permissive, most patterns subsume it
]


def detect_patterns(
    df: pd.DataFrame,
    bar_idx:          int           = -2,
    direction_filter: Optional[str] = None,
    enabled:          Optional[List[str]] = None,
) -> List[PatternMatch]:
    """
    Run every detector on a bar. Returns all matches.

    direction_filter: if "BUY" or "SELL", only return matches in that direction
                      (note: contextual patterns like inside_bar carry a
                      placeholder direction and `details["directional"] = False`
                      — caller is responsible for treating those specially).
    enabled:          if provided, only run detectors whose pattern name is
                      in this list. Names: pin_bar matches both 'hammer' and
                      'shooting_star'; engulfing matches 'bullish_engulfing'
                      and 'bearish_engulfing'.
    """
    out: List[PatternMatch] = []
    for det in ALL_DETECTORS:
        m = det(df, bar_idx=bar_idx)
        if m is None:
            continue
        if enabled is not None and m.name not in enabled and _detector_alias(det) not in enabled:
            continue
        if direction_filter is not None:
            if m.details.get("directional", True) is False:
                # contextual pattern — caller decides; include unconditionally
                out.append(m)
                continue
            if m.direction != direction_filter:
                continue
        out.append(m)
    return out


def _detector_alias(det) -> str:
    """Map a detector function to its config-friendly alias name."""
    return det.__name__.replace("detect_", "")


# ── Self-tests ────────────────────────────────────────────────────────────────


def _make_df(rows):
    """rows: list of (open, high, low, close) tuples."""
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])


def _run_self_tests():
    failures = []

    def check(name, condition, detail=""):
        if not condition:
            failures.append(f"  [FAIL] {name}: {detail}")
            print(f"  [FAIL] {name}: {detail}")
        else:
            print(f"  [OK]   {name}")

    print("Pin bar / hammer:")
    df = _make_df([
        (100, 101, 99, 100),
        (100, 100.5, 95, 99.8),    # long lower wick, small body near top
    ])
    m = detect_pin_bar(df, bar_idx=-1)
    check("hammer detected", m is not None and m.name == "hammer", str(m))
    check("hammer direction is BUY", m and m.direction == DIR_BUY)

    print("Pin bar / shooting star:")
    df = _make_df([
        (100, 101, 99, 100),
        (100, 105, 99.5, 100.2),   # long upper wick, small body near bottom
    ])
    m = detect_pin_bar(df, bar_idx=-1)
    check("shooting_star detected", m is not None and m.name == "shooting_star", str(m))
    check("shooting_star direction is SELL", m and m.direction == DIR_SELL)

    print("Pin bar negative (big body, no wick):")
    df = _make_df([
        (100, 101, 99, 100),
        (100, 105, 99.5, 104.8),   # huge body, small wicks → not a pin
    ])
    m = detect_pin_bar(df, bar_idx=-1)
    check("rejects big-body bar", m is None, str(m))

    print("Bullish engulfing:")
    df = _make_df([
        (100, 100.5, 99, 99.5),     # small bearish
        (99, 102, 98.5, 101.5),     # bullish engulfs body 99→99.5 with body 99→101.5
    ])
    m = detect_engulfing(df, bar_idx=-1)
    check("bullish_engulfing detected", m is not None and m.name == "bullish_engulfing", str(m))
    check("bullish_engulfing direction BUY", m and m.direction == DIR_BUY)

    print("Bearish engulfing:")
    df = _make_df([
        (99, 100, 98.5, 99.5),      # small bullish
        (100, 100.5, 97, 98.5),     # bearish, body 100→98.5 engulfs 99→99.5
    ])
    m = detect_engulfing(df, bar_idx=-1)
    check("bearish_engulfing detected", m is not None and m.name == "bearish_engulfing", str(m))

    print("Engulfing rejects same color:")
    df = _make_df([
        (99, 100, 98.5, 99.5),      # bullish small
        (98, 101, 97, 100),          # bullish big — not an engulfing reversal
    ])
    m = detect_engulfing(df, bar_idx=-1)
    check("rejects same-color engulf", m is None, str(m))

    print("Inside bar:")
    df = _make_df([
        (100, 105, 95, 102),         # mother
        (101, 103, 99, 102),         # baby inside mother
    ])
    m = detect_inside_bar(df, bar_idx=-1)
    check("inside_bar detected", m is not None and m.name == "inside_bar", str(m))
    check("inside_bar marked non-directional", m and m.details.get("directional") is False)

    print("Inside bar negative (baby outside):")
    df = _make_df([
        (100, 105, 95, 102),
        (101, 106, 99, 102),         # high exceeds mother's high
    ])
    m = detect_inside_bar(df, bar_idx=-1)
    check("rejects non-inside", m is None, str(m))

    print("Tweezers top:")
    df = _make_df([
        (98, 102, 97, 101),          # bullish, high 102
        (101, 102, 98, 99),          # bearish, high 102 — matches
    ])
    m = detect_tweezers_top(df, bar_idx=-1)
    check("tweezers_top detected", m is not None, str(m))

    print("Tweezers bottom:")
    df = _make_df([
        (101, 102, 98, 99),          # bearish, low 98
        (99, 102, 98, 101),          # bullish, low 98 — matches
    ])
    m = detect_tweezers_bottom(df, bar_idx=-1)
    check("tweezers_bottom detected", m is not None, str(m))

    print("Morning star:")
    df = _make_df([
        (100, 100.5, 95, 95.5),      # large bearish (body 100→95.5)
        (95, 96, 94.5, 95.5),        # small body
        (95.5, 99, 95, 98.5),        # bullish, closes 98.5 > midpoint (97.75)
    ])
    m = detect_morning_star(df, bar_idx=-1)
    check("morning_star detected", m is not None, str(m))

    print("Morning star negative (third doesn't reach midpoint):")
    df = _make_df([
        (100, 100.5, 95, 95.5),
        (95, 96, 94.5, 95.5),
        (95.5, 97, 95, 96.5),        # closes 96.5 < midpoint 97.75
    ])
    m = detect_morning_star(df, bar_idx=-1)
    check("rejects shallow third candle", m is None, str(m))

    print("Evening star:")
    df = _make_df([
        (95, 100.5, 94.5, 100),      # large bullish (body 95→100)
        (100, 101, 99.5, 100.5),     # small body
        (100, 100.5, 95, 95.5),      # bearish, closes 95.5 < midpoint 97.5
    ])
    m = detect_evening_star(df, bar_idx=-1)
    check("evening_star detected", m is not None, str(m))

    print("Dragonfly doji:")
    df = _make_df([
        (100, 100, 95, 100),         # open=close=high, long lower
    ])
    m = detect_dragonfly_doji(df, bar_idx=-1)
    check("dragonfly_doji detected", m is not None, str(m))

    print("Gravestone doji:")
    df = _make_df([
        (100, 105, 100, 100),        # open=close=low, long upper
    ])
    m = detect_gravestone_doji(df, bar_idx=-1)
    check("gravestone_doji detected", m is not None, str(m))

    print("Doji:")
    df = _make_df([
        (100, 102, 98, 100),         # body 0
    ])
    m = detect_doji(df, bar_idx=-1)
    check("doji detected", m is not None, str(m))

    print("Orchestrator runs all detectors:")
    df = _make_df([
        (100, 101, 99, 100),
        (100, 100.5, 95, 99.8),      # hammer
    ])
    matches = detect_patterns(df, bar_idx=-1)
    check("orchestrator finds hammer", any(m.name == "hammer" for m in matches),
          f"matches={[m.name for m in matches]}")

    print("Direction filter:")
    matches_buy = detect_patterns(df, bar_idx=-1, direction_filter=DIR_BUY)
    matches_sell = detect_patterns(df, bar_idx=-1, direction_filter=DIR_SELL)
    check("BUY filter keeps hammer", any(m.name == "hammer" for m in matches_buy))
    check("SELL filter drops hammer", not any(m.name == "hammer" for m in matches_sell))

    print()
    if failures:
        print(f"FAIL: {len(failures)} test(s) failed:")
        for f in failures:
            print(f)
        return 1
    print("All self-tests passed.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_self_tests())