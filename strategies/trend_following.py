"""
strategies/trend_following.py
──────────────────────────────
Strong Trend Following Strategy
──────────────────────────────
LOGIC:
  BUY signal:
    1. EMA(20) > EMA(50) > EMA(200) (Bullish Alignment)
    2. Price > EMA(20) (Price Above Fast EMA)
    3. ADX(14) > 25 (Strong Trend Strength)
    4. RSI(14) > 50 (Bullish Momentum)
  SELL signal:
    1. EMA(20) < EMA(50) < EMA(200) (Bearish Alignment)
    2. Price < EMA(20) (Price Below Fast EMA)
    3. ADX(14) > 25 (Strong Trend Strength)
    4. RSI(14) < 50 (Bearish Momentum)

INDICATORS:
  EMA Fast   : 20-period
  EMA Medium : 50-period
  EMA Slow   : 200-period
  ADX        : 14-period (Trend Strength)
  RSI        : 14-period (Momentum)
  ATR        : 14-period (Volatility for SL/TP)
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from config.settings import settings
from utils.logger import logger
from strategies.base_strategy import BaseStrategy


@dataclass
class SignalResult:
    signal: str            # BUY | SELL | NONE
    pair: str
    close: float
    ema_20: float
    ema_50: float
    ema_200: float
    rsi: float
    adx: float
    atr: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""

    def __str__(self):
        return (
            f"Signal: {self.signal} | {self.pair} | Close: {self.close:.5f} | "
            f"EMA20: {self.ema_20:.5f} | EMA50: {self.ema_50:.5f} | EMA200: {self.ema_200:.5f} | "
            f"ADX: {self.adx:.2f} | RSI: {self.rsi:.2f} | ATR: {self.atr:.5f}"
        )


class TrendFollowingStrategy(BaseStrategy):
    """
    Trend Following Strategy focusing on strong trends.
    """

    def __init__(self):
        self.ema_fast_period = 20
        self.ema_medium_period = 50
        self.ema_slow_period = 200
        self.adx_period = 14
        self.rsi_period = 14
        self.atr_period = 14
        self.adx_threshold = 25

        logger.info(
            f"Strategy loaded: Strong Trend Following | "
            f"EMAs: {self.ema_fast_period}/{self.ema_medium_period}/{self.ema_slow_period} | "
            f"ADX > {self.adx_threshold} | RSI 50 Filter"
        )

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate indicators for trend following."""
        # EMA 200 needs more data for stabilization (at least 20-30 extra candles)
        min_required = self.ema_slow_period + 30
        if len(df) < min_required:
            raise ValueError(
                f"Not enough data: need at least {min_required} candles. "
                f"Currently have {len(df)}. Tip: Scroll back in MT5 chart to download more history."
            )

        # EMAs
        df["ema_20"] = EMAIndicator(close=df["close"], window=self.ema_fast_period).ema_indicator()
        df["ema_50"] = EMAIndicator(close=df["close"], window=self.ema_medium_period).ema_indicator()
        df["ema_200"] = EMAIndicator(close=df["close"], window=self.ema_slow_period).ema_indicator()

        # ADX
        adx_ind = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=self.adx_period)
        df["adx"] = adx_ind.adx()

        # RSI
        df["rsi"] = RSIIndicator(close=df["close"], window=self.rsi_period).rsi()

        # ATR for SL/TP
        df["atr"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=self.atr_period).average_true_range()

        return df

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        """Analyze market data for strong trend signals."""
        try:
            df = self.calculate_indicators(df)
            curr = df.iloc[-1]
            
            # Need recent data for HH/LL calculation
            recent_period = 20
            recent_data = df.iloc[-recent_period:]

            close = curr["close"]
            ema20 = curr["ema_20"]
            ema50 = curr["ema_50"]
            ema200 = curr["ema_200"]
            adx = curr["adx"]
            rsi = curr["rsi"]
            atr = curr["atr"]

            signal = "NONE"
            reason = ""

            # Check Trend Alignment & Strength
            is_uptrend = (ema20 > ema50 > ema200) and (close > ema20)
            is_downtrend = (ema20 < ema50 < ema200) and (close < ema20)
            is_strong = adx > self.adx_threshold

            if is_uptrend and is_strong and rsi > 50:
                signal = "BUY"
                reason = "Strong Bullish Trend & Momentum"
            elif is_downtrend and is_strong and rsi < 50:
                signal = "SELL"
                reason = "Strong Bearish Trend & Momentum"
            else:
                if not is_strong:
                    reason = f"Weak Trend (ADX: {adx:.1f} < {self.adx_threshold})"
                elif not (is_uptrend or is_downtrend):
                    reason = "Trend EMA Mismatch"
                else:
                    reason = f"RSI Neutral/Opposing (RSI: {rsi:.1f})"

            # Calculate SL/TP if signal
            sl, tp = None, None
            if signal != "NONE":
                # ─── Strategic SL & Flexible TP Logic ──────────────────────
                # SL: Recent High/Low + ATR Buffer for "Breathing Room"
                # This ensures the SL is placed where a trend break is confirmed.
                
                atr_buffer = atr * settings.ATR_MULTIPLIER_SL
                
                if signal == "BUY":
                    # Strategic SL: Recent Low (20 candles)
                    recent_low = recent_data["low"].min()
                    sl = recent_low - atr_buffer
                    
                    # Ensure SL isn't TOO far or TOO close
                    max_sl = close * (1 - settings.MAX_SL_DISTANCE_PCT)
                    min_sl = close - (atr * 0.5)
                    sl = max(min(sl, min_sl), max_sl)
                    
                    # TP: Target 5x ATR for a wider run, but we will monitor momentum
                    tp = close + (atr * settings.ATR_MULTIPLIER_TP)
                    
                else: # SELL
                    # Strategic SL: Recent High (20 candles)
                    recent_high = recent_data["high"].max()
                    sl = recent_high + atr_buffer
                    
                    # Ensure SL isn't TOO far or TOO close
                    max_sl = close * (1 + settings.MAX_SL_DISTANCE_PCT)
                    min_sl = close + (atr * 0.5)
                    sl = min(max(sl, min_sl), max_sl)
                    
                    # TP: Target 5x ATR for a wider run, but we will monitor momentum
                    tp = close - (atr * settings.ATR_MULTIPLIER_TP)

            return SignalResult(
                signal=signal,
                pair=pair,
                close=close,
                ema_20=ema20,
                ema_50=ema50,
                ema_200=ema200,
                rsi=rsi,
                adx=adx,
                atr=atr,
                stop_loss=sl,
                take_profit=tp,
                reason=reason
            )

        except Exception as e:
            logger.error(f"Error in TrendFollowingStrategy.analyse: {e}")
            return SignalResult(signal="NONE", pair=pair, close=0, ema_20=0, ema_50=0, ema_200=0, rsi=0, adx=0, atr=0, reason=str(e))

    def check_exit(self, curr: pd.Series, trade: dict) -> tuple[bool, str]:
        """Check for strategy-based exit (Trend Reversal)."""
        close = curr["close"]
        ema20 = curr["ema_20"]
        ema50 = curr["ema_50"]
        
        direction = trade.get("direction")
        
        if direction == "BUY":
            # Exit if price drops below EMA 50 or EMA 20 crosses below EMA 50
            if close < ema50 or ema20 < ema50:
                return True, "Bullish Trend Weakened/Reversed"
        elif direction == "SELL":
            # Exit if price rises above EMA 50 or EMA 20 crosses above EMA 50
            if close > ema50 or ema20 > ema50:
                return True, "Bearish Trend Weakened/Reversed"
                
        return False, ""
