"""
strategies/ema_rsi.py
─────────────────────
EMA Crossover + RSI Filter Strategy
────────────────────────────────────
LOGIC:
  BUY  signal: EMA_fast crosses ABOVE EMA_slow AND RSI > RSI_UPPER (50)
  SELL signal: EMA_fast crosses BELOW EMA_slow AND RSI < RSI_LOWER (50)

INDICATORS:
  EMA Fast  : 9-period  Exponential Moving Average
  EMA Slow  : 21-period Exponential Moving Average
  RSI       : 14-period Relative Strength Index
  ATR       : 14-period Average True Range (for SL/TP calculation)

RISK MANAGEMENT:
  Stop Loss   : Entry ± (ATR × ATR_MULTIPLIER_SL)
  Take Profit : Entry ± (ATR × ATR_MULTIPLIER_TP)
  Risk/Reward : Minimum 2:1 (3.0 TP / 1.5 SL multipliers)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
from ta.trend    import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from config.settings import settings
from utils.logger import logger


# ─── Signal Result Dataclass ──────────────────────────────
@dataclass
class SignalResult:
    signal:      str            # BUY | SELL | NONE
    pair:        str
    close:       float
    ema_fast:    float
    ema_slow:    float
    rsi:         float
    atr:         float
    adx:         float = 0.0
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None
    reason:      str = ""

    def __str__(self):
        return (
            f"Signal: {self.signal} | {self.pair} | Close: {self.close:.5f} | "
            f"EMA9: {self.ema_fast:.5f} | EMA21: {self.ema_slow:.5f} | "
            f"RSI: {self.rsi:.2f} | ATR: {self.atr:.5f} | "
            f"SL: {self.stop_loss} | TP: {self.take_profit}"
        )


class EMARSIStrategy:
    """
    EMA Crossover + RSI Filter Strategy.
    Instantiate once and call analyse() on each candle batch.
    """

    def __init__(self):
        self.ema_fast_period = settings.EMA_FAST
        self.ema_slow_period = settings.EMA_SLOW
        self.ema_trend_period = settings.EMA_TREND_PERIOD
        self.adx_period = 14         # ADX for trend strength
        self.adx_threshold = settings.ADX_THRESHOLD
        self.rsi_period      = settings.RSI_PERIOD
        self.rsi_upper       = settings.RSI_UPPER
        self.rsi_lower       = settings.RSI_LOWER
        self.atr_period      = settings.ATR_PERIOD
        # self.atr_sl_mult     = settings.ATR_MULTIPLIER_SL (Removed: Using fixed SL %)
        self.atr_tp_mult     = settings.ATR_MULTIPLIER_TP

        logger.info(
            f"Strategy loaded: EMA({self.ema_fast_period}/{self.ema_slow_period}) + "
            f"Trend EMA({self.ema_trend_period}) + "
            f"ADX({self.adx_period})>{self.adx_threshold} + "
            f"RSI({self.rsi_period}) | SL=Fixed% | TP=Dynamic(ATR×{self.atr_tp_mult})"
        )

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators and add them to the DataFrame.
        Requires columns: open, high, low, close, volume
        Returns the same DataFrame with added indicator columns.
        """
        min_required = max(self.ema_slow_period, self.rsi_period, self.atr_period, self.adx_period) + 5
        if len(df) < min_required:
            raise ValueError(f"Not enough data: need at least {min_required} candles")

        # ── EMA Fast & Slow ───────────────────────────────
        df["ema_fast"] = EMAIndicator(
            close=df["close"], window=self.ema_fast_period
        ).ema_indicator()

        df["ema_slow"] = EMAIndicator(
            close=df["close"], window=self.ema_slow_period
        ).ema_indicator()
        
        # ── EMA Trend (200) ──────────────────────────────
        # Only calculate if we have enough data
        if len(df) >= self.ema_trend_period:
            df["ema_trend"] = EMAIndicator(
                close=df["close"], window=self.ema_trend_period
            ).ema_indicator()
        else:
            df["ema_trend"] = np.nan

        # ── RSI ───────────────────────────────────────────
        df["rsi"] = RSIIndicator(
            close=df["close"], window=self.rsi_period
        ).rsi()

        # ── ATR (for SL/TP calculation) ───────────────────
        df["atr"] = AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"],
            window=self.atr_period
        ).average_true_range()

        # ── ADX ───────────────────────────────────────────
        df["adx"] = ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"],
            window=self.adx_period
        ).adx()

        # ── Crossover detection ───────────────────────────
        # ema_fast_prev: EMA fast value one candle ago
        df["ema_fast_prev"] = df["ema_fast"].shift(1)
        df["ema_slow_prev"] = df["ema_slow"].shift(1)

        # Bullish crossover: fast was below slow, now above
        df["bullish_cross"] = (
            (df["ema_fast_prev"] <= df["ema_slow_prev"]) &
            (df["ema_fast"]      >  df["ema_slow"])
        )

        # Bearish crossover: fast was above slow, now below
        df["bearish_cross"] = (
            (df["ema_fast_prev"] >= df["ema_slow_prev"]) &
            (df["ema_fast"]      <  df["ema_slow"])
        )

        df.dropna(subset=["ema_fast", "ema_slow", "rsi", "atr", "adx"], inplace=True)
        return df

    def _calculate_sl_tp(self, price: float, atr: float) -> tuple[float, float]:
        """
        Calculate SL and TP distances using standardized ATR settings.
        SL = 1.5 * ATR (High Probability)
        TP = 1.5 * ATR (1:1 Risk:Reward for Small Wins)
        """
        sl_dist = atr * settings.ATR_MULTIPLIER_SL
        tp_dist = atr * settings.ATR_MULTIPLIER_TP
        return sl_dist, tp_dist

    def check_signal(self, curr: pd.Series, pair: str) -> SignalResult:
        close    = float(curr["close"])
        ema_fast = float(curr["ema_fast"])
        ema_slow = float(curr["ema_slow"])
        # Check if we have EMA 200 data
        ema_trend = float(curr["ema_trend"]) if "ema_trend" in curr and not pd.isna(curr["ema_trend"]) else None
        
        rsi      = float(curr["rsi"])
        atr      = float(curr["atr"])
        adx      = float(curr["adx"])
        bull_x   = bool(curr["bullish_cross"])
        bear_x   = bool(curr["bearish_cross"])

        # ── BUY Signal ────────────────────────────────────
        # Trend Filter: Only Buy if Price > EMA 200 (if available)
        trend_ok_buy = (close > ema_trend) if ema_trend else True
        
        # RSI Filter: Avoid buying at the top (RSI > 70)
        # We want RSI > 50 (Momentum) but < 70 (Not Overbought)
        rsi_buy_ok = self.rsi_upper < rsi < 70

        if bull_x:
            if rsi_buy_ok:
                if trend_ok_buy:
                    if adx > self.adx_threshold:
                        sl_dist, tp_dist = self._calculate_sl_tp(close, atr)
                        
                        sl = round(close - sl_dist, 5)
                        tp = round(close + tp_dist, 5)
                        return SignalResult(
                            signal="BUY", pair=pair,
                            close=close, ema_fast=ema_fast, ema_slow=ema_slow,
                            rsi=rsi, atr=atr, adx=adx,
                            stop_loss=sl, take_profit=tp,
                            reason=f"EMA Bull Cross + RSI {rsi:.1f} (Valid) + Trend OK + ADX {adx:.1f}"
                        )
                    else:
                        reason = f"Bullish Cross + RSI OK ({rsi:.1f}) but ADX {adx:.1f} <= {self.adx_threshold}"
                else:
                    reason = f"Bullish Cross + RSI OK ({rsi:.1f}) but Price < EMA200 (Trend Filter)"
            else:
                reason = f"Bullish Cross but RSI {rsi:.1f} not in range {self.rsi_upper}-70"
        
        # ── SELL Signal ───────────────────────────────────
        trend_ok_sell = (close < ema_trend) if ema_trend else True
        
        # RSI Filter: Avoid selling at the bottom (RSI < 30)
        # We want RSI < 50 (Momentum) but > 30 (Not Oversold)
        rsi_sell_ok = 30 < rsi < self.rsi_lower

        if bear_x:
            if rsi_sell_ok:
                if trend_ok_sell:
                    if adx > self.adx_threshold:
                        sl_dist, tp_dist = self._calculate_sl_tp(close, atr)
                        
                        sl = round(close + sl_dist, 5)
                        tp = round(close - tp_dist, 5)
                        return SignalResult(
                            signal="SELL", pair=pair,
                            close=close, ema_fast=ema_fast, ema_slow=ema_slow,
                            rsi=rsi, atr=atr, adx=adx,
                            stop_loss=sl, take_profit=tp,
                            reason=f"EMA Bear Cross + RSI {rsi:.1f} (Valid) + Trend OK + ADX {adx:.1f}"
                        )
                    else:
                        reason = f"Bearish Cross + RSI OK ({rsi:.1f}) but ADX {adx:.1f} <= {self.adx_threshold}"
                else:
                    reason = f"Bearish Cross + RSI OK ({rsi:.1f}) but Price > EMA200 (Trend Filter)"
            else:
                reason = f"Bearish Cross but RSI {rsi:.1f} not in range 30-{self.rsi_lower}"

        return SignalResult(
            signal="NONE", pair=pair,
            close=close, ema_fast=ema_fast, ema_slow=ema_slow,
            rsi=rsi, atr=atr, adx=adx,
            reason=reason if 'reason' in locals() else "No signal"
        )

    def check_exit(self, curr: pd.Series, trade: dict) -> tuple:
        """
        Check if an open trade should be closed early based on reversal signals.
        Returns: (bool, str) -> (should_close, reason)
        """
        direction = trade["direction"]
        close     = float(curr["close"])
        ema_fast  = float(curr["ema_fast"])
        ema_slow  = float(curr["ema_slow"])
        rsi       = float(curr["rsi"])

        # ── BUY Exit Logic ────────────────────────────────
        if direction == "BUY":
            # 1. Bearish Crossover (Trend Reversal)
            if ema_fast < ema_slow:
                return True, f"Early Exit: Bearish Crossover (EMA9 {ema_fast:.5f} < EMA21 {ema_slow:.5f})"
            
            # 2. RSI Overbought Reversal (Momentum Loss)
            # If RSI was high and drops below 50, momentum is gone
            if rsi < 50:
                 return True, f"Early Exit: Momentum Loss (RSI {rsi:.1f} < 50)"

        # ── SELL Exit Logic ───────────────────────────────
        elif direction == "SELL":
            # 1. Bullish Crossover (Trend Reversal)
            if ema_fast > ema_slow:
                return True, f"Early Exit: Bullish Crossover (EMA9 {ema_fast:.5f} > EMA21 {ema_slow:.5f})"
            
            # 2. RSI Oversold Reversal (Momentum Loss)
            # If RSI was low and goes above 50, momentum is gone
            if rsi > 50:
                return True, f"Early Exit: Momentum Loss (RSI {rsi:.1f} > 50)"

        return False, ""

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        """
        Analyse the latest candle and return a SignalResult.
        Call this after fetch_ohlcv() returns fresh data.
        """
        try:
            df = self.calculate_indicators(df.copy())
        except Exception as e:
            logger.warning(f"[{pair}] Indicator calculation failed: {e}")
            return SignalResult(
                signal="NONE", pair=pair, close=0,
                ema_fast=0, ema_slow=0, rsi=0, atr=0,
                reason=str(e)
            )

        # Get the most recent completed candle (index -1 is current forming candle)
        # We need at least 2 rows to have a completed candle
        if len(df) < 2:
             logger.warning(f"[{pair}] Not enough data after indicator calculation. Got {len(df)} rows.")
             return SignalResult(
                signal="NONE", pair=pair, close=0,
                ema_fast=0, ema_slow=0, rsi=0, atr=0,
                reason="Not enough data"
            )

        latest = df.iloc[-2]
        return self.check_signal(latest, pair)

    def _no_signal_reason(self, bull_x: bool, bear_x: bool, rsi: float) -> str:
        if bull_x and rsi <= self.rsi_upper:
            return f"Bullish cross but RSI {rsi:.1f} not above {self.rsi_upper} (weak momentum)"
        if bear_x and rsi >= self.rsi_lower:
            return f"Bearish cross but RSI {rsi:.1f} not below {self.rsi_lower} (weak momentum)"
        return "No crossover detected"

    def get_summary(self, df: pd.DataFrame) -> dict:
        """Return a dict summary of current indicator values for logging."""
        try:
            df = self.calculate_indicators(df.copy())
        except Exception:
            close = float(df["close"].iloc[-1]) if "close" in df.columns and len(df) else 0.0
            return {
                "close": close,
                "ema_fast": 0.0,
                "ema_slow": 0.0,
                "rsi": 0.0,
                "atr": 0.0,
                "bullish_cross": False,
                "bearish_cross": False,
            }

        if len(df) < 2:
            close = float(df["close"].iloc[-1]) if "close" in df.columns and len(df) else 0.0
            return {
                "close": close,
                "ema_fast": 0.0,
                "ema_slow": 0.0,
                "rsi": 0.0,
                "atr": 0.0,
                "bullish_cross": False,
                "bearish_cross": False,
            }

        latest = df.iloc[-2]
        return {
            "close":        round(float(latest["close"]), 5),
            "ema_fast":     round(float(latest["ema_fast"]), 5),
            "ema_slow":     round(float(latest["ema_slow"]), 5),
            "rsi":          round(float(latest["rsi"]), 2),
            "atr":          round(float(latest["atr"]), 5),
            "bullish_cross":bool(latest["bullish_cross"]),
            "bearish_cross":bool(latest["bearish_cross"]),
        }
