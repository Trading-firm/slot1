
import pandas as pd
import numpy as np
import ta
from dataclasses import dataclass
from typing import Optional, Tuple
from config.settings import settings
from strategies.base_strategy import BaseStrategy

@dataclass
class SignalResult:
    signal: str      # "BUY", "SELL", "NONE"
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    support: float = 0.0
    resistance: float = 0.0

class SupportResistanceStrategy(BaseStrategy):
    """
    Enhanced Support and Resistance Strategy.
    Identifies recent Swing Highs (Resistance) and Swing Lows (Support).
    Buys at Support, Sells at Resistance.
    Includes ADX Filter (Ranging Market) and RSI Filter (Momentum).
    """

    def __init__(self, window: int = 20, tolerance_pct: float = 0.001):
        self.window = window
        self.tolerance_pct = tolerance_pct # 0.1% tolerance for "touching" the level

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Support = Minimum Low of last N periods (excluding current)
        # Resistance = Maximum High of last N periods (excluding current)
        
        # We shift by 1 to avoid lookahead bias (using current candle to define the level it's testing)
        df['support'] = df['low'].shift(1).rolling(window=self.window).min()
        df['resistance'] = df['high'].shift(1).rolling(window=self.window).max()
        
        # Trend Filter: EMA 200
        df['ema_200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()

        # ADX Filter: Strength of trend
        adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
        df['adx'] = adx.adx()

        # RSI Filter: Momentum
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

        # ATR for SL/TP
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        
        return df

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        """
        Analyse the latest candle and return a SignalResult.
        """
        if len(df) < 200: # Need 200 for EMA
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df.copy())
        
        # Use the last COMPLETED candle (index -2) to avoid repainting
        curr = df.iloc[-2]
        return self.check_signal(curr, pair)

    def check_signal(self, curr: pd.Series, pair: str) -> SignalResult:
        close = float(curr["close"])
        high = float(curr["high"])
        low = float(curr["low"])
        support = float(curr["support"])
        resistance = float(curr["resistance"])
        ema_200 = float(curr["ema_200"])
        adx = float(curr["adx"])
        rsi = float(curr["rsi"])
        atr = float(curr["atr"])
        
        if pd.isna(support) or pd.isna(resistance) or pd.isna(atr):
            return SignalResult("NONE", pair, close)

        # Calculate tolerance distance
        # tol_dist = close * self.tolerance_pct # Not used directly, using percentage check below
        
        # Get dynamic settings for this pair
        atr_mult_sl, atr_mult_tp = self._get_sl_tp_settings(pair)

        # ── BUY at Support ────────────────────────────────
        # Logic: Low touched Support area, but Close bounced up
        # 1. Low went below Support + Tolerance (Tested level)
        # 2. Close is above Support (Held level)
        touched_support = low <= support * (1 + self.tolerance_pct)
        bounced_up = close > support
        
        # Filters:
        # 1. ADX < 25 (Ranging Market) - S/R works best in ranges
        # 2. RSI < 60 (Not Overbought, room to grow)
        # 3. EMA Trend Filter (Optional: Only Buy if Close > EMA 200 for Trend Pullback, 
        #    OR ignore EMA if ADX is very low (pure range))
        # Let's use strict Range logic: ADX < 30 (Weak Trend/Range)
        
        valid_buy = touched_support and bounced_up and (adx < 30) and (rsi < 60)
        
        if valid_buy:
             # SL based on ATR
             sl_dist = atr * atr_mult_sl
             sl = close - sl_dist
             
             # TP based on ATR (1:1 Ratio)
             tp_dist = atr * atr_mult_tp
             tp_target = close + tp_dist
             
             return SignalResult(
                 "BUY", pair, close, sl, tp_target,
                 reason=f"Support Bounce (S:{support:.5f}, ADX:{adx:.1f}, RSI:{rsi:.1f})"
             )

        # ── SELL at Resistance ────────────────────────────
        # Logic: High touched Resistance area, but Close bounced down
        # 1. High went above Resistance - Tolerance (Tested level)
        # 2. Close is below Resistance (Held level)
        touched_resistance = high >= resistance * (1 - self.tolerance_pct)
        bounced_down = close < resistance
        
        # Filters:
        # 1. ADX < 30 (Ranging Market)
        # 2. RSI > 40 (Not Oversold, room to fall)
        
        valid_sell = touched_resistance and bounced_down and (adx < 30) and (rsi > 40)
        
        if valid_sell:
             # SL based on ATR
             sl_dist = atr * atr_mult_sl
             sl = close + sl_dist
             
             # TP based on ATR (1:1 Ratio)
             tp_dist = atr * atr_mult_tp
             tp_target = close - tp_dist
             
             return SignalResult(
                 "SELL", pair, close, sl, tp_target,
                 reason=f"Resistance Rejection (R:{resistance:.5f}, ADX:{adx:.1f}, RSI:{rsi:.1f})"
             )

        return SignalResult("NONE", pair, close, support=support, resistance=resistance)

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        direction = trade["direction"]
        close = float(curr["close"])
        rsi = float(curr["rsi"])
        # ema_200 = float(curr["ema_200"]) # Optional

        # Early Exit Logic
        if direction == "BUY":
            # Exit if RSI becomes Overbought (Reversal risk)
            if rsi > 75:
                return True, f"Early Exit: Overbought (RSI {rsi:.1f} > 75)"
                
        elif direction == "SELL":
            # Exit if RSI becomes Oversold (Reversal risk)
            if rsi < 25:
                return True, f"Early Exit: Oversold (RSI {rsi:.1f} < 25)"

        return False, ""
