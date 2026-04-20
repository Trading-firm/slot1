"""
strategies/signal_engine.py
────────────────────────────
Trend-Following Signal Engine for BTCUSD.
Uses ADX for trend strength and EMA Pullbacks for entry.

Filters (in order of application):
  1. Session window (WAT timezone)
  2. ADX minimum (strong trend required)
  3. EMA trend alignment (EMA50 vs EMA200)
  4. Pullback to EMA20 with bullish/bearish close
  5. RSI pullback confirmation (momentum cooled off)
  6. Higher timeframe (H1) trend alignment
"""

from datetime import datetime, timedelta
import math
import pandas as pd
from dataclasses import dataclass
from strategies.indicators import (
    calc_ema, calc_rsi, calc_atr, calc_adx,
    calc_bollinger_bands,
    calc_fvg, calc_order_blocks, calc_liquidity_levels, calc_swing_points
)
from utils.logger import logger


@dataclass
class Signal:
    symbol:     str
    direction:  str
    reason:     str
    base_signal:str
    close:      float
    atr:        float
    sl:         float
    tp1:        float
    tp2:        float
    tp3:        float
    rsi:        float
    ema_trend:  float


def generate_signal(
    df: pd.DataFrame,
    cfg: dict,
    htf_df: pd.DataFrame = None,   # Optional H1 dataframe for HTF confirmation
) -> Signal:
    symbol   = cfg["symbol"]
    strategy = cfg["strategy"]
    filters  = cfg.get("filters", {})

    # ─── Scalper dispatch ─────────────────────────────────
    # Momentum candle scalper. Reads live spread from MT5 if available.
    if strategy == "scalper":
        from strategies.scalper import generate_scalp_signal
        try:
            import MetaTrader5 as mt5
            si = mt5.symbol_info(symbol)
            spread_price = (si.spread * si.point) if si else 0.0
        except Exception:
            spread_price = 0.0

        scalp = generate_scalp_signal(df, cfg, spread_price=spread_price)
        if scalp.direction == "NONE":
            return _empty_signal(symbol, scalp.entry, 0.0, 0.0, 0.0,
                                 base_signal="NONE", reason=scalp.reason)
        logger.info(f"[{symbol}] SCALP {scalp.direction} | {scalp.reason} | "
                    f"entry~{scalp.entry:.5f} SL:{scalp.sl:.5f} TP:{scalp.tp:.5f}")
        return Signal(
            symbol      = symbol,
            direction   = scalp.direction,
            reason      = scalp.reason,
            base_signal = scalp.direction,
            close       = scalp.entry,
            atr         = 0.0,   # scalper uses structural SL, atr=0 disables BE trailing
            sl          = round(scalp.sl, 5),
            tp1         = round(scalp.tp, 5),
            tp2         = round(scalp.tp, 5),
            tp3         = round(scalp.tp, 5),
            rsi         = 0.0,
            ema_trend   = 0.0,
        )

    # ─── Indicators ────────────────────────────────────────
    atr_vals   = calc_atr(df, cfg.get("atr_period", 14))
    rsi_vals   = calc_rsi(df, cfg.get("rsi_period", 14))
    ema_f_vals = calc_ema(df, filters.get("ema_fast", 20))
    ema_s_vals = calc_ema(df, filters.get("ema_slow", 50))
    ema_t_vals = calc_ema(df, filters.get("ema_trend", 200))
    adx_vals   = calc_adx(df, filters.get("adx_period", 14))

    idx      = -2  # last completed candle
    close    = df["Close"].iloc[idx]
    atr      = atr_vals.iloc[idx]
    rsi      = rsi_vals.iloc[idx]
    ema_f    = ema_f_vals.iloc[idx]
    ema_s    = ema_s_vals.iloc[idx]
    ema_t    = ema_t_vals.iloc[idx]
    adx      = adx_vals.iloc[idx]

    # Guard against NaN indicators (not enough data)
    if any(math.isnan(v) for v in [atr, rsi, ema_f, ema_s, ema_t, adx]):
        return _empty_signal(symbol, close, 0.0, 0.0, 0.0, "NONE", "Indicators not ready (insufficient data)")

    direction = "NONE"
    reason    = ""
    base_dir  = "NONE"

    # ─── Session Filter (WAT Timezone) ────────────────────
    sessions = filters.get("sessions", [])
    if sessions:
        if "time" in df.columns:
            candle_time_utc = df["time"].iloc[idx]
        else:
            candle_time_utc = df.index[idx]

        if not isinstance(candle_time_utc, datetime):
            candle_time_utc = pd.to_datetime(candle_time_utc)

        candle_time_wat = candle_time_utc + timedelta(hours=1)
        curr_hour_wat   = candle_time_wat.hour

        in_session = False
        for s in sessions:
            if s["start"] <= curr_hour_wat <= s["end"]:
                in_session = True
                break

        if not in_session:
            logger.warning(f"[{symbol}] Entry blocked — Outside trading sessions (WAT: {curr_hour_wat}:00)")
            return _empty_signal(symbol, close, atr, rsi, ema_t, "NONE", "Outside trading session")

    # ─── Trend-Following Strategy ─────────────────────────
    if strategy == "trend_following":
        adx_min = filters.get("adx_min", 25)

        uptrend      = ema_s > ema_t and close > ema_t
        downtrend    = ema_s < ema_t and close < ema_t
        strong_trend = adx > adx_min

        curr_open     = df["Open"].iloc[idx]
        curr_low      = df["Low"].iloc[idx]
        curr_high     = df["High"].iloc[idx]
        candle_bull   = close > curr_open   # Bullish candle close
        candle_bear   = close < curr_open   # Bearish candle close

        # RSI must show that momentum has cooled during the pullback:
        # For BUY: RSI between 35–58  (pullback, not oversold or still overbought)
        # For SELL: RSI between 42–65 (pullback, not overbought or still oversold)
        rsi_ok_buy  = filters.get("rsi_min_buy",  35) <= rsi <= filters.get("rsi_max_buy",  58)
        rsi_ok_sell = filters.get("rsi_min_sell", 42) <= rsi <= filters.get("rsi_max_sell", 65)

        # Pullback tolerance — fraction of ATR the low/high may deviate from EMA20
        # and still count as a valid pullback touch. 0.0 = strict (must touch).
        pullback_tol = filters.get("pullback_tol", 0.0) * atr

        if strong_trend:
            # ── Pullback to EMA20 Entry ─────────────────────
            # Requires:
            #   • Low reached (or came within pullback_tol ATR of) EMA20
            #   • Candle CLOSED back above/below EMA20 (rejection confirmed)
            #   • Bullish/bearish candle (direction confirmed)
            #   • RSI cooled into the pullback zone
            if uptrend and curr_low <= ema_f + pullback_tol and close > ema_f and candle_bull and rsi_ok_buy:
                base_dir = "BUY"
                reason   = f"Trend: EMA20 Pullback + Bullish Close | RSI:{rsi:.0f} ADX:{adx:.1f}"

            elif downtrend and curr_high >= ema_f - pullback_tol and close < ema_f and candle_bear and rsi_ok_sell:
                base_dir = "SELL"
                reason   = f"Trend: EMA20 Pullback + Bearish Close | RSI:{rsi:.0f} ADX:{adx:.1f}"

    # ─── SMC (Smart Money Concepts) Strategy ──────────────
    elif strategy == "smc":
        fvgs = calc_fvg(df)
        obs  = calc_order_blocks(df)

        curr_open  = df["Open"].iloc[idx]
        curr_close = df["Close"].iloc[idx]
        curr_high  = df["High"].iloc[idx]
        curr_low   = df["Low"].iloc[idx]

        last_fvg = None
        for i in range(idx, idx-30, -1):
            if fvgs[i] and fvgs[i]["type"] == "BULLISH":
                last_fvg = fvgs[i]
                break

        if last_fvg:
            for ob in reversed(obs):
                if ob["type"] == "BULLISH" and ob["top"] < last_fvg["bottom"]:
                    if curr_low <= ob["top"] and curr_close > curr_open:
                        base_dir = "BUY"
                        reason   = "SMC: Bullish Rejection from OB after FVG"
                        break

        if base_dir == "NONE":
            last_fvg = None
            for i in range(idx, idx-30, -1):
                if fvgs[i] and fvgs[i]["type"] == "BEARISH":
                    last_fvg = fvgs[i]
                    break
            if last_fvg:
                for ob in reversed(obs):
                    if ob["type"] == "BEARISH" and ob["bottom"] > last_fvg["top"]:
                        if curr_high >= ob["bottom"] and curr_close < curr_open:
                            base_dir = "SELL"
                            reason   = "SMC: Bearish Rejection from OB after FVG"
                            break

    # ─── Breakout Strategy ────────────────────────────────
    elif strategy == "breakout":
        upper, lower = calc_bollinger_bands(df, 20)
        prev_close   = df["Close"].iloc[idx-1]
        prev_upper   = upper.iloc[idx-1]
        prev_lower   = lower.iloc[idx-1]

        if close > ema_t and close > upper.iloc[idx] and prev_close <= prev_upper:
            base_dir = "BUY"
            reason   = "Breakout: Price closed above BB Upper + EMA200 Trend"
        elif close < ema_t and close < lower.iloc[idx] and prev_close >= prev_lower:
            base_dir = "SELL"
            reason   = "Breakout: Price closed below BB Lower + EMA200 Trend"

    # ─── No base signal ───────────────────────────────────
    if base_dir == "NONE":
        return _empty_signal(symbol, close, atr, rsi, ema_t)

    logger.info(
        f"[{symbol}] Base signal: {base_dir} | {reason} | "
        f"ADX:{adx:.1f} | Close:{close:.2f} | EMA200:{ema_t:.2f}"
    )

    # ─── Higher Timeframe (H1) Confirmation ───────────────
    # Only allow trades that align with the H1 trend direction.
    # A BUY on M15 during an H1 downtrend is counter-trend — skip it.
    if htf_df is not None and not htf_df.empty and len(htf_df) >= 200:
        htf_ema_s = calc_ema(htf_df, filters.get("ema_slow",  50)).iloc[-2]
        htf_ema_t = calc_ema(htf_df, filters.get("ema_trend", 200)).iloc[-2]

        htf_uptrend   = htf_ema_s > htf_ema_t
        htf_downtrend = htf_ema_s < htf_ema_t

        if base_dir == "BUY" and not htf_uptrend:
            logger.warning(f"[{symbol}] BUY blocked — H1 not in uptrend (H1 EMA50:{htf_ema_s:.0f} < EMA200:{htf_ema_t:.0f})")
            return _empty_signal(symbol, close, atr, rsi, ema_t, "BUY", "H1 trend mismatch")

        if base_dir == "SELL" and not htf_downtrend:
            logger.warning(f"[{symbol}] SELL blocked — H1 not in downtrend (H1 EMA50:{htf_ema_s:.0f} > EMA200:{htf_ema_t:.0f})")
            return _empty_signal(symbol, close, atr, rsi, ema_t, "SELL", "H1 trend mismatch")

        logger.info(f"[{symbol}] H1 trend confirmed: {base_dir}")

    direction = base_dir
    logger.info(f"[{symbol}] All filters passed — {direction}")

    # ─── SL / TP Structural Logic ─────────────────────────
    swing_window = cfg.get("swing_window", 10)
    highs, lows  = calc_swing_points(df, window=swing_window)

    recent_low   = lows.iloc[idx-swing_window : idx].min()
    recent_high  = highs.iloc[idx-swing_window : idx].max()

    max_sl_dist  = atr * cfg.get("max_sl_atr", 2.5)

    if direction == "BUY":
        sl      = recent_low - (atr * 0.2)
        sl_dist = close - sl

        if sl_dist > max_sl_dist:
            logger.warning(f"[{symbol}] BUY skipped — SL too far ({sl_dist:.2f} > {max_sl_dist:.2f})")
            return _empty_signal(symbol, close, atr, rsi, ema_t, direction, "SL too far")

        tp1 = close + (sl_dist * 1.0)
        tp2 = close + (sl_dist * 2.0)
        tp3 = recent_high
        if tp3 <= tp2 + (atr * 0.5):
            tp3 = close + (sl_dist * 3.0)

    elif direction == "SELL":
        sl      = recent_high + (atr * 0.2)
        sl_dist = sl - close

        if sl_dist > max_sl_dist:
            logger.warning(f"[{symbol}] SELL skipped — SL too far ({sl_dist:.2f} > {max_sl_dist:.2f})")
            return _empty_signal(symbol, close, atr, rsi, ema_t, direction, "SL too far")

        tp1 = close - (sl_dist * 1.0)
        tp2 = close - (sl_dist * 2.0)
        tp3 = recent_low
        if tp3 >= tp2 - (atr * 0.5):
            tp3 = close - (sl_dist * 3.0)
    else:
        sl, tp1, tp2, tp3 = 0.0, 0.0, 0.0, 0.0

    return Signal(
        symbol      = symbol,
        direction   = direction,
        reason      = reason,
        base_signal = base_dir,
        close       = close,
        atr         = atr,
        sl          = round(sl, 5),
        tp1         = round(tp1, 5),
        tp2         = round(tp2, 5),
        tp3         = round(tp3, 5),
        rsi         = round(rsi, 2),
        ema_trend   = round(ema_t, 5),
    )


def check_invalidation(df: pd.DataFrame, trade: dict, cfg: dict) -> tuple:
    """
    Checks if the current market structure invalidates the open trade.
    Returns (True, reason) if invalidated, else (False, "").
    """
    # Scalper trades are short-lived — let SL/TP handle exit.
    if cfg.get("strategy") == "scalper":
        return False, ""

    direction  = trade["direction"]
    idx        = -1
    close      = df["Close"].iloc[idx]
    ema_t_vals = calc_ema(df, cfg.get("filters", {}).get("ema_trend", 200))
    ema_t      = ema_t_vals.iloc[idx]

    if direction == "BUY"  and close < ema_t:
        return True,  "Trend Flip: Price closed below EMA200"
    if direction == "SELL" and close > ema_t:
        return True,  "Trend Flip: Price closed above EMA200"

    return False, ""


def _empty_signal(
    symbol, close, atr, rsi, ema_t,
    base_signal="NONE", reason="No base signal"
) -> Signal:
    return Signal(
        symbol      = symbol,
        direction   = "NONE",
        reason      = reason,
        base_signal = base_signal,
        close       = close,
        atr         = atr,
        sl          = 0.0,
        tp1         = 0.0,
        tp2         = 0.0,
        tp3         = 0.0,
        rsi         = round(rsi, 2)  if rsi  else 0.0,
        ema_trend   = round(ema_t, 5) if ema_t else 0.0,
    )
