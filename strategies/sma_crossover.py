
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Tuple, Optional
from config.settings import settings
from strategies.base_strategy import BaseStrategy

@dataclass
class SignalResult:
    signal: str
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""

class SMACrossoverStrategy(BaseStrategy):
    def __init__(self, fast=50, slow=200):
        self.fast = fast
        self.slow = slow
        self.atr_tp_mult = settings.ATR_MULTIPLIER_TP

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        sma_fast = ta.trend.SMAIndicator(close=df["close"], window=self.fast)
        sma_slow = ta.trend.SMAIndicator(close=df["close"], window=self.slow)
        
        df["sma_fast"] = sma_fast.sma_indicator()
        df["sma_slow"] = sma_slow.sma_indicator()
        
        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["atr"] = atr.average_true_range()
        
        # RSI (Momentum Confirmation)
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=14)
        df["rsi"] = rsi.rsi()

        # ADX (Trend Strength)
        adx = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["adx"] = adx.adx()
        
        return df


    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        adx = float(curr["adx"])
        rsi = float(curr["rsi"])
        
        # Filter: ADX > 20 (Ensure Trend Strength)
        if adx < 20:
             return SignalResult("NONE", pair, curr["close"], reason=f"Weak Trend (ADX {adx:.1f} < 20)")

        # Get dynamic settings for this pair
        sl_mult, tp_mult = self._get_sl_tp_settings(pair)

        # Golden Cross
        # 1. Fast SMA crosses above Slow SMA
        # 2. RSI is < 70 (Not Overbought)
        if prev["sma_fast"] < prev["sma_slow"] and curr["sma_fast"] > curr["sma_slow"]:
            if rsi > 70:
                 return SignalResult("NONE", pair, curr["close"], reason=f"Overbought (RSI {rsi:.1f})")

            sl_dist = curr["atr"] * sl_mult
            tp_dist = curr["atr"] * tp_mult
            
            sl = curr["close"] - sl_dist
            tp = curr["close"] + tp_dist
            return SignalResult("BUY", pair, curr["close"], sl, tp, reason="SMA Golden Cross + Trend Confirmed")
            
        # Death Cross
        # 1. Fast SMA crosses below Slow SMA
        # 2. RSI is > 30 (Not Oversold)
        elif prev["sma_fast"] > prev["sma_slow"] and curr["sma_fast"] < curr["sma_slow"]:
            if rsi < 30:
                 return SignalResult("NONE", pair, curr["close"], reason=f"Oversold (RSI {rsi:.1f})")

            sl_dist = curr["atr"] * sl_mult
            tp_dist = curr["atr"] * tp_mult
            
            sl = curr["close"] + sl_dist
            tp = curr["close"] - tp_dist
            return SignalResult("SELL", pair, curr["close"], sl, tp, reason="SMA Death Cross + Trend Confirmed")
            
        return SignalResult("NONE", pair, curr["close"], reason="No crossover")

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Check if we should exit the trade early based on strategy logic.
        """
        direction = trade["direction"]
        
        # Exit Buy if Death Cross (Fast crosses below Slow)
        if direction == "BUY":
            if curr["sma_fast"] < curr["sma_slow"]:
                 return True, "Exit Signal: SMA Death Cross"
                 
        # Exit Sell if Golden Cross (Fast crosses above Slow)
        elif direction == "SELL":
             if curr["sma_fast"] > curr["sma_slow"]:
                 return True, "Exit Signal: SMA Golden Cross"
                 
        return False, ""

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < self.slow + 10:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        return self.check_signal(curr, prev, pair)
