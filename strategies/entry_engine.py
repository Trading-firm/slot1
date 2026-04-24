"""
strategies/entry_engine.py
───────────────────────────
Phase 4: Entry engine — pure price action, no candlestick body checks.

Consumes:
  - MTF bias (Phase 2)
  - Active + recently-broken levels (Phase 3)
  - M15 DataFrame (for local swing detection)

Emits EntrySetup (direction, entry, sl, tp_a, tp_b, invalidation_price).

Scenarios handled:
  A. Trend-pullback entry — H4 UPTREND + M15 forms new higher low (or DOWNTREND + new lower high)
  B. Range-reversal entry — price near H4 range bound + M15 confirms higher low / lower high at bound
  C. Range-breakout entry — price closed beyond H4 range bound (no candle-body filter, close-based only)

Defaults scoped for gold at 0.01 lot; Phase 6 will tune per market.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from strategies.market_structure import find_swing_points
from strategies.mtf_analysis import (
    MTFReport, BIAS_BUY, BIAS_SELL, BIAS_RANGE, BIAS_NEUTRAL,
)
from strategies.level_memory import (
    LevelMemory, LVL_SWING_HIGH, LVL_SWING_LOW, LVL_RANGE_TOP, LVL_RANGE_BOTTOM,
)


SCENARIO_TREND_PULLBACK = "trend_pullback"
SCENARIO_RANGE_REVERSAL = "range_reversal"
SCENARIO_RANGE_BREAKOUT = "range_breakout"
SCENARIO_LEVEL_TOUCH    = "level_touch"
SCENARIO_SWEEP_RECLAIM  = "sweep_reclaim"


@dataclass
class EntrySetup:
    direction:             str        # "BUY" or "SELL"
    entry_price:           float      # market entry estimate (last M15 close)
    sl:                    float      # structural SL (below higher-low for BUY, mirror for SELL)
    tp_a:                  float      # main trade TP (structural, min 1:3)
    tp_b_profit_usd:       float      # trade B closes when live P/L reaches this $ value
    invalidation_price:    float      # Phase 5 active monitor closes A if M15 closes beyond this
    scenario:              str        # which scenario fired
    reason:                str        # human-readable


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Simple ATR from the last `period` M15 bars."""
    if len(df) < period + 1:
        return 0.0
    high = df["High"].tail(period + 1).values
    low  = df["Low"].tail(period + 1).values
    close_prev = df["Close"].tail(period + 1).shift(1).values
    trs = []
    for i in range(1, len(high)):
        tr = max(high[i] - low[i], abs(high[i] - close_prev[i]), abs(low[i] - close_prev[i]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def _in_session(bar_time, sessions) -> bool:
    """
    sessions: list of [start_hour, end_hour] UTC pairs. None/empty = always on.
    Handles wrap-around (e.g., [[22, 6]] = 22:00-06:00 UTC).
    """
    if not sessions:
        return True
    try:
        hour = int(bar_time.hour)
    except AttributeError:
        return True
    for sess in sessions:
        start, end = int(sess[0]), int(sess[1])
        if start <= end:
            if start <= hour < end:
                return True
        else:
            if hour >= start or hour < end:
                return True
    return False


def _detect_trend_pullback(
    mtf: MTFReport,
    level_memory: LevelMemory,
    df_m15: pd.DataFrame,
    symbol: str,
    max_lookback_bars: int = 20,
    swing_left: int = 5,
    swing_right: int = 5,
    min_rr: float = 3.0,
    tp_b_usd: float = 2.0,
) -> Optional[EntrySetup]:
    """
    Scenario A: H4 trending, wait for M15 pullback to complete (new higher/lower swing).
    """
    swings = find_swing_points(df_m15, left=swing_left, right=swing_right)
    if len(swings) < 2:
        return None

    last_close = float(df_m15["Close"].iloc[-2])   # last CLOSED bar

    if mtf.bias == BIAS_BUY:
        lows = [s for s in swings if s.kind == "LOW"]
        if len(lows) < 2:
            return None
        last_low, prev_low = lows[-1], lows[-2]

        # Must be (a) higher than previous low (confirms uptrend) (b) recent (c) price now above it
        if last_low.price <= prev_low.price:
            return None
        if len(df_m15) - 1 - last_low.idx > max_lookback_bars:
            return None
        if last_close <= last_low.price:
            return None

        entry = last_close
        sl    = last_low.price - 0.0001
        sl_dist = entry - sl
        if sl_dist <= 0:
            return None

        # TP: exact min_rr target, but respect structure —
        # if an H4 level sits BETWEEN entry and the target, use the level (don't plow through it).
        target_tp = entry + sl_dist * min_rr
        candidate = level_memory.get_nearest(symbol, entry, "above", timeframe="H4")
        if candidate and candidate.price < target_tp:
            tp_a = candidate.price
        else:
            tp_a = target_tp

        return EntrySetup(
            direction="BUY",
            entry_price=entry,
            sl=sl,
            tp_a=tp_a,
            tp_b_profit_usd=tp_b_usd,
            invalidation_price=last_low.price,
            scenario=SCENARIO_TREND_PULLBACK,
            reason=f"H4 UPTREND; M15 higher low at ${last_low.price:.2f} (prev ${prev_low.price:.2f}); SL below pullback",
        )

    if mtf.bias == BIAS_SELL:
        highs = [s for s in swings if s.kind == "HIGH"]
        if len(highs) < 2:
            return None
        last_high, prev_high = highs[-1], highs[-2]

        if last_high.price >= prev_high.price:
            return None
        if len(df_m15) - 1 - last_high.idx > max_lookback_bars:
            return None
        if last_close >= last_high.price:
            return None

        entry = last_close
        sl    = last_high.price + 0.0001
        sl_dist = sl - entry
        if sl_dist <= 0:
            return None

        target_tp = entry - sl_dist * min_rr
        candidate = level_memory.get_nearest(symbol, entry, "below", timeframe="H4")
        if candidate and candidate.price > target_tp:
            tp_a = candidate.price
        else:
            tp_a = target_tp

        return EntrySetup(
            direction="SELL",
            entry_price=entry,
            sl=sl,
            tp_a=tp_a,
            tp_b_profit_usd=tp_b_usd,
            invalidation_price=last_high.price,
            scenario=SCENARIO_TREND_PULLBACK,
            reason=f"H4 DOWNTREND; M15 lower high at ${last_high.price:.2f} (prev ${prev_high.price:.2f}); SL above rally",
        )

    return None


def _detect_range_reversal(
    mtf: MTFReport,
    level_memory: LevelMemory,
    df_m15: pd.DataFrame,
    symbol: str,
    near_bound_atr: float = 1.5,          # price within 1.5 ATR = "near" a bound (M15 ATR ~$12 → $18)
    swing_near_bound_atr: float = 2.5,    # the confirming swing can be up to 2.5 ATR from bound
    max_lookback_bars: int = 30,
    swing_left: int = 5,
    swing_right: int = 5,
    min_rr: float = 3.0,
    tp_b_usd: float = 2.0,
) -> Optional[EntrySetup]:
    """
    Scenario B: H4 RANGE; price near a bound AND M15 confirms reversal with a higher low / lower high at the bound.
    """
    if mtf.bias != BIAS_RANGE or mtf.range_bounds is None:
        return None

    support, resistance = mtf.range_bounds
    last_close = float(df_m15["Close"].iloc[-2])
    atr = _atr(df_m15)
    if atr <= 0:
        return None
    nearby = near_bound_atr * atr

    swings = find_swing_points(df_m15, left=swing_left, right=swing_right)
    lows  = [s for s in swings if s.kind == "LOW"]
    highs = [s for s in swings if s.kind == "HIGH"]

    swing_near = swing_near_bound_atr * atr

    # BUY near support
    if abs(last_close - support) <= nearby and len(lows) >= 2:
        last_low, prev_low = lows[-1], lows[-2]
        if (last_low.price > prev_low.price and
            len(df_m15) - 1 - last_low.idx <= max_lookback_bars and
            abs(last_low.price - support) <= swing_near and       # the higher low itself is near support
            last_close > last_low.price):
            entry = last_close
            sl = last_low.price - 0.0001
            sl_dist = entry - sl
            if sl_dist > 0:
                # TP = exact min_rr target, capped at range top if range top is closer
                target_tp = entry + sl_dist * min_rr
                tp_a = min(resistance, target_tp) if resistance > entry else target_tp
                return EntrySetup(
                    direction="BUY", entry_price=entry, sl=sl, tp_a=tp_a,
                    tp_b_profit_usd=tp_b_usd,
                    invalidation_price=last_low.price,
                    scenario=SCENARIO_RANGE_REVERSAL,
                    reason=f"H4 RANGE BUY at support ${support:.2f}; M15 higher low ${last_low.price:.2f} confirms",
                )

    # SELL near resistance
    if abs(last_close - resistance) <= nearby and len(highs) >= 2:
        last_high, prev_high = highs[-1], highs[-2]
        if (last_high.price < prev_high.price and
            len(df_m15) - 1 - last_high.idx <= max_lookback_bars and
            abs(last_high.price - resistance) <= swing_near and
            last_close < last_high.price):
            entry = last_close
            sl = last_high.price + 0.0001
            sl_dist = sl - entry
            if sl_dist > 0:
                target_tp = entry - sl_dist * min_rr
                tp_a = max(support, target_tp) if support < entry else target_tp
                return EntrySetup(
                    direction="SELL", entry_price=entry, sl=sl, tp_a=tp_a,
                    tp_b_profit_usd=tp_b_usd,
                    invalidation_price=last_high.price,
                    scenario=SCENARIO_RANGE_REVERSAL,
                    reason=f"H4 RANGE SELL at resistance ${resistance:.2f}; M15 lower high ${last_high.price:.2f} confirms",
                )

    return None


def _detect_range_breakout(
    mtf: MTFReport,
    level_memory: LevelMemory,
    df_m15: pd.DataFrame,
    symbol: str,
    breakout_lookback_min: int = 30,
    min_rr: float = 3.0,
    tp_b_usd: float = 2.0,
) -> Optional[EntrySetup]:
    """
    Scenario C: H4 RANGE but price just CLOSED beyond a bound — trade the breakout direction.
    Uses level_memory.get_recently_broken to find recent H4-level breaks.
    """
    if mtf.bias != BIAS_RANGE or mtf.range_bounds is None:
        return None
    support, resistance = mtf.range_bounds

    last_close = float(df_m15["Close"].iloc[-2])
    atr = _atr(df_m15)
    if atr <= 0:
        return None

    # Find recently broken H4 range top/bottom
    broken = level_memory.get_recently_broken(symbol, within_minutes=breakout_lookback_min)
    broken_h4 = [b for b in broken if b.timeframe == "H4" and b.type in (LVL_RANGE_TOP, LVL_RANGE_BOTTOM)]

    # Breakout UP (close > resistance)
    if last_close > resistance:
        if broken_h4 and any(b.type == LVL_RANGE_TOP for b in broken_h4):
            entry = last_close
            sl = resistance - 0.0001                       # back inside range = invalidation
            sl_dist = entry - sl
            if sl_dist <= 0: return None
            # TP: exact min_rr target. Measured move is larger; we prefer the reachable target.
            tp_a = entry + sl_dist * min_rr
            return EntrySetup(
                direction="BUY", entry_price=entry, sl=sl, tp_a=tp_a,
                tp_b_profit_usd=tp_b_usd,
                invalidation_price=resistance,
                scenario=SCENARIO_RANGE_BREAKOUT,
                reason=f"H4 RANGE BREAKOUT above ${resistance:.2f}; target measured move",
            )

    # Breakdown (close < support)
    if last_close < support:
        if broken_h4 and any(b.type == LVL_RANGE_BOTTOM for b in broken_h4):
            entry = last_close
            sl = support + 0.0001
            sl_dist = sl - entry
            if sl_dist <= 0: return None
            tp_a = entry - sl_dist * min_rr
            return EntrySetup(
                direction="SELL", entry_price=entry, sl=sl, tp_a=tp_a,
                tp_b_profit_usd=tp_b_usd,
                invalidation_price=support,
                scenario=SCENARIO_RANGE_BREAKOUT,
                reason=f"H4 RANGE BREAKDOWN below ${support:.2f}; target measured move",
            )

    return None


def _count_prior_touches(df: pd.DataFrame, swing_idx: int, swing_price: float,
                          swing_kind: str, tol: float) -> int:
    """How many bars AFTER the swing formed have tested its price without breaking."""
    count = 0
    n = len(df)
    if swing_idx + 1 >= n - 1:
        return 0
    for i in range(swing_idx + 1, n - 1):   # exclude in-progress bar
        bh = float(df["High"].iloc[i])
        bl = float(df["Low"].iloc[i])
        bc = float(df["Close"].iloc[i])
        if swing_kind == "LOW":
            # Tested = bar low touched/dipped past, but close stayed above (no break)
            if bl <= swing_price + tol and bc > swing_price:
                count += 1
        else:
            if bh >= swing_price - tol and bc < swing_price:
                count += 1
    return count


def _detect_sweep_reclaim(
    mtf: MTFReport,
    level_memory: LevelMemory,
    df_m15: pd.DataFrame,
    symbol: str,
    sl_buffer_atr:       float = 0.2,
    max_lookback_bars:   int   = 30,
    swing_left:          int   = 5,
    swing_right:         int   = 5,
    min_rr:              float = 1.5,
    tp_b_usd:            float = 2.0,
    min_prior_touches:   int   = 1,
    min_body_ratio:      float = 0.4,     # close in top/bottom (1-min_body_ratio) of bar
    min_sweep_atr:       float = 0.1,     # wick must sweep past level by at least this
) -> Optional[EntrySetup]:
    """
    Liquidity-sweep reversal: price wicked past a recent swing level AND closed back
    through it. Classic stop-hunt rejection — the highest-WR pattern on crypto M15.

    BUY:  bar_low  < swing_low  AND bar_close > swing_low  AND close in upper portion
    SELL: bar_high > swing_high AND bar_close < swing_high AND close in lower portion

    SL goes below the sweep wick (not just the swing) so the "trap" can't be re-set
    without stopping us out legitimately.
    """
    atr = _atr(df_m15)
    if atr <= 0:
        return None
    sl_buf = atr * sl_buffer_atr
    min_sweep = atr * min_sweep_atr

    bar_high  = float(df_m15["High"].iloc[-2])
    bar_low   = float(df_m15["Low"].iloc[-2])
    bar_close = float(df_m15["Close"].iloc[-2])
    bar_range = bar_high - bar_low
    if bar_range <= 0:
        return None
    close_pos = (bar_close - bar_low) / bar_range   # 0=at low, 1=at high

    swings = find_swing_points(df_m15, left=swing_left, right=swing_right)
    recent = [s for s in swings if len(df_m15) - 1 - s.idx <= max_lookback_bars]
    touch_tol = atr * 0.3   # for prior-touch counting

    # ── BUY sweep (BUY bias or RANGE) ──
    if mtf.bias in (BIAS_BUY, BIAS_RANGE) and close_pos >= (1.0 - min_body_ratio):
        for sw in reversed([s for s in recent if s.kind == "LOW"]):
            swept_by = sw.price - bar_low
            if swept_by < min_sweep:
                continue
            if bar_close <= sw.price:
                continue
            if min_prior_touches > 0:
                touches = _count_prior_touches(
                    df_m15.iloc[:-1], sw.idx, sw.price, "LOW", touch_tol,
                )
                if touches < min_prior_touches:
                    continue
            if mtf.bias == BIAS_RANGE and mtf.range_bounds:
                # Only accept sweeps in the lower half of the range
                if sw.price > (mtf.range_bounds[0] + mtf.range_bounds[1]) / 2:
                    continue
            entry = bar_close
            sl    = bar_low - sl_buf
            sl_dist = entry - sl
            if sl_dist <= 0:
                continue
            tp_a = entry + sl_dist * min_rr
            return EntrySetup(
                direction="BUY", entry_price=entry, sl=sl, tp_a=tp_a,
                tp_b_profit_usd=tp_b_usd,
                invalidation_price=sw.price,
                scenario=SCENARIO_SWEEP_RECLAIM,
                reason=(f"BUY sweep-reclaim: swept swing-low ${sw.price:.2f} to ${bar_low:.2f}, "
                        f"closed ${bar_close:.2f} ({close_pos*100:.0f}% of bar)"),
            )

    # ── SELL sweep (SELL bias or RANGE) ──
    if mtf.bias in (BIAS_SELL, BIAS_RANGE) and close_pos <= min_body_ratio:
        for sw in reversed([s for s in recent if s.kind == "HIGH"]):
            swept_by = bar_high - sw.price
            if swept_by < min_sweep:
                continue
            if bar_close >= sw.price:
                continue
            if min_prior_touches > 0:
                touches = _count_prior_touches(
                    df_m15.iloc[:-1], sw.idx, sw.price, "HIGH", touch_tol,
                )
                if touches < min_prior_touches:
                    continue
            if mtf.bias == BIAS_RANGE and mtf.range_bounds:
                if sw.price < (mtf.range_bounds[0] + mtf.range_bounds[1]) / 2:
                    continue
            entry = bar_close
            sl    = bar_high + sl_buf
            sl_dist = sl - entry
            if sl_dist <= 0:
                continue
            tp_a = entry - sl_dist * min_rr
            return EntrySetup(
                direction="SELL", entry_price=entry, sl=sl, tp_a=tp_a,
                tp_b_profit_usd=tp_b_usd,
                invalidation_price=sw.price,
                scenario=SCENARIO_SWEEP_RECLAIM,
                reason=(f"SELL sweep-reclaim: swept swing-high ${sw.price:.2f} to ${bar_high:.2f}, "
                        f"closed ${bar_close:.2f} ({close_pos*100:.0f}% of bar)"),
            )

    return None


def _detect_level_touch(
    mtf: MTFReport,
    level_memory: LevelMemory,
    df_m15: pd.DataFrame,
    symbol: str,
    touch_tolerance_atr: float = 0.3,
    sl_buffer_atr:       float = 0.3,
    max_lookback_bars:   int   = 30,
    swing_left:          int   = 5,
    swing_right:         int   = 5,
    min_rr:              float = 2.0,
    tp_b_usd:            float = 2.0,
    min_prior_touches:   int   = 1,        # require level was tested at least N times before
    min_body_ratio:      float = 0.4,      # close in top/bottom (1-min_body_ratio) of bar
) -> Optional[EntrySetup]:
    """
    Fires on the FIRST CONTACT with an S/R level, not after a new swing forms.

    For BIAS_BUY:   bar's low touches a recent M15 swing low, close stays above → BUY
    For BIAS_SELL:  bar's high touches a recent M15 swing high, close stays below → SELL
    For BIAS_RANGE: both directions allowed at matching range bounds.

    Never trades against the H4 bias (never BUY in BIAS_SELL).
    """
    atr = _atr(df_m15)
    if atr <= 0:
        return None
    tol = atr * touch_tolerance_atr
    sl_buf = atr * sl_buffer_atr

    last_high  = float(df_m15["High"].iloc[-2])   # last CLOSED bar
    last_low   = float(df_m15["Low"].iloc[-2])
    last_close = float(df_m15["Close"].iloc[-2])
    bar_range  = last_high - last_low
    if bar_range <= 0:
        return None
    close_pos = (last_close - last_low) / bar_range   # 0=at low, 1=at high

    swings = find_swing_points(df_m15, left=swing_left, right=swing_right)
    recent = [s for s in swings if len(df_m15) - 1 - s.idx <= max_lookback_bars]
    swing_lows  = [s for s in recent if s.kind == "LOW"]
    swing_highs = [s for s in recent if s.kind == "HIGH"]

    # ── BUY branch (only in BIAS_BUY or BIAS_RANGE) ──
    # Close must be in upper (1-min_body_ratio) of bar — strong rejection, not weak touch
    if mtf.bias in (BIAS_BUY, BIAS_RANGE) and close_pos >= (1.0 - min_body_ratio):
        for sw in reversed(swing_lows):   # most recent first
            # Bar tested the swing low AND closed above it (rejection)
            if last_low <= sw.price + tol and last_close > sw.price:
                # Quality filter: level must have proven itself with prior touches
                if min_prior_touches > 0:
                    touches = _count_prior_touches(
                        df_m15.iloc[:-1], sw.idx, sw.price, "LOW", tol,
                    )
                    if touches < min_prior_touches:
                        continue
                entry = last_close
                sl = sw.price - sl_buf
                sl_dist = entry - sl
                if sl_dist <= 0:
                    continue
                # In BIAS_RANGE, prefer lows NEAR the range bottom (higher quality)
                if mtf.bias == BIAS_RANGE and mtf.range_bounds:
                    range_bottom = mtf.range_bounds[0]
                    # swing must be in lower half of range (closer to support)
                    if sw.price > (mtf.range_bounds[0] + mtf.range_bounds[1]) / 2:
                        continue
                # TP = exact min_rr target. No nearest-level capping — that caused
                # sub-1R TPs that lose money to spread. Rely on the structural
                # invalidation monitor to exit early if thesis breaks.
                tp_a = entry + sl_dist * min_rr
                return EntrySetup(
                    direction="BUY", entry_price=entry, sl=sl, tp_a=tp_a,
                    tp_b_profit_usd=tp_b_usd,
                    invalidation_price=sw.price,
                    scenario=SCENARIO_LEVEL_TOUCH,
                    reason=f"BUY bounce off M15 swing low ${sw.price:.2f} (bar low ${last_low:.2f} close ${last_close:.2f}, {close_pos*100:.0f}% of bar)",
                )

    # ── SELL branch (only in BIAS_SELL or BIAS_RANGE) ──
    if mtf.bias in (BIAS_SELL, BIAS_RANGE) and close_pos <= min_body_ratio:
        for sw in reversed(swing_highs):
            if last_high >= sw.price - tol and last_close < sw.price:
                if min_prior_touches > 0:
                    touches = _count_prior_touches(
                        df_m15.iloc[:-1], sw.idx, sw.price, "HIGH", tol,
                    )
                    if touches < min_prior_touches:
                        continue
                entry = last_close
                sl = sw.price + sl_buf
                sl_dist = sl - entry
                if sl_dist <= 0:
                    continue
                if mtf.bias == BIAS_RANGE and mtf.range_bounds:
                    # swing must be in upper half of range
                    if sw.price < (mtf.range_bounds[0] + mtf.range_bounds[1]) / 2:
                        continue
                tp_a = entry - sl_dist * min_rr
                return EntrySetup(
                    direction="SELL", entry_price=entry, sl=sl, tp_a=tp_a,
                    tp_b_profit_usd=tp_b_usd,
                    invalidation_price=sw.price,
                    scenario=SCENARIO_LEVEL_TOUCH,
                    reason=f"SELL rejection off M15 swing high ${sw.price:.2f} (bar high ${last_high:.2f} close ${last_close:.2f}, {close_pos*100:.0f}% of bar)",
                )

    return None


def find_entry(
    mtf:          MTFReport,
    level_memory: LevelMemory,
    df_m15:       pd.DataFrame,
    symbol:       str,
    cfg:          Optional[dict] = None,
) -> Optional[EntrySetup]:
    """
    Orchestrator. Picks the right scenario for the current bias.

    Scenario priority (highest WR first):
      1. sweep_reclaim  — stop-hunt reversal (crypto's highest-WR pattern)
      2. level_touch    — standard S/R rejection
      3. range_reversal — only in H4 RANGE regime
      4. range_breakout / trend_pullback — disabled by default (historically net-negative)

    Session filter (cfg['sessions']) blocks ALL scenarios outside London/NY hours
    where crypto M15 tends to chop.
    """
    if mtf.bias == BIAS_NEUTRAL:
        return None

    cfg = cfg or {}
    tp_b_usd = cfg.get("tp_b_profit_usd", 2.0)
    min_rr   = cfg.get("min_rr", 1.5)
    near_bound_atr       = cfg.get("near_bound_atr", 1.5)
    swing_near_bound_atr = cfg.get("swing_near_bound_atr", 2.5)
    max_lookback_bars    = cfg.get("max_lookback_bars", 30)
    breakout_lookback_min = cfg.get("breakout_lookback_min", 30)
    min_prior_touches    = cfg.get("min_prior_touches", 2)
    min_body_ratio       = cfg.get("min_body_ratio", 0.4)
    sl_buffer_atr_sweep  = cfg.get("sl_buffer_atr_sweep", 0.2)
    min_sweep_atr        = cfg.get("min_sweep_atr", 0.1)

    # Session filter — reject entries outside configured UTC hours
    sessions = cfg.get("sessions", [])
    if sessions and "time" in df_m15.columns and len(df_m15) >= 2:
        bar_time = df_m15["time"].iloc[-2]
        if not _in_session(bar_time, sessions):
            return None

    # Per-scenario kill switches
    enable_sweep    = cfg.get("enable_sweep_reclaim",  True)
    enable_touch    = cfg.get("enable_level_touch",    True)
    enable_reversal = cfg.get("enable_range_reversal", False)
    enable_breakout = cfg.get("enable_range_breakout", False)
    enable_pullback = cfg.get("enable_trend_pullback", False)

    if enable_sweep:
        setup = _detect_sweep_reclaim(
            mtf, level_memory, df_m15, symbol,
            sl_buffer_atr=sl_buffer_atr_sweep,
            max_lookback_bars=max_lookback_bars,
            min_rr=min_rr, tp_b_usd=tp_b_usd,
            min_prior_touches=min_prior_touches,
            min_body_ratio=min_body_ratio,
            min_sweep_atr=min_sweep_atr,
        )
        if setup: return setup

    if enable_touch:
        setup = _detect_level_touch(
            mtf, level_memory, df_m15, symbol,
            max_lookback_bars=max_lookback_bars, min_rr=min_rr, tp_b_usd=tp_b_usd,
            min_prior_touches=min_prior_touches,
            min_body_ratio=min_body_ratio,
        )
        if setup: return setup

    if enable_reversal:
        setup = _detect_range_reversal(
            mtf, level_memory, df_m15, symbol,
            near_bound_atr=near_bound_atr, swing_near_bound_atr=swing_near_bound_atr,
            max_lookback_bars=max_lookback_bars, min_rr=min_rr, tp_b_usd=tp_b_usd,
        )
        if setup: return setup

    if enable_breakout:
        setup = _detect_range_breakout(
            mtf, level_memory, df_m15, symbol,
            breakout_lookback_min=breakout_lookback_min, min_rr=min_rr, tp_b_usd=tp_b_usd,
        )
        if setup: return setup

    if enable_pullback:
        setup = _detect_trend_pullback(
            mtf, level_memory, df_m15, symbol,
            max_lookback_bars=max_lookback_bars, min_rr=min_rr, tp_b_usd=tp_b_usd,
        )
        if setup: return setup

    return None
