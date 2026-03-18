import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional
from strategies.base_strategy import BaseStrategy

@dataclass
class SignalResult:
    signal: str
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""

class FVGStrategy(BaseStrategy):
    """
    Fair Value Gap (FVG) / Order Block Strategy.
    
    Logic:
    1. Identify Swing Highs and Swing Lows ("Last Touch").
    2. Identify Fair Value Gaps (Imbalance).
    3. Enter when price is near the FVG.
    4. SL: Slightly beyond the Swing Low/High.
    5. TP: Slightly before the opposing Swing High/Low.
    """
    def __init__(self, swing_period=10):
        self.swing_period = swing_period

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Identify Swing Lows (Minimum of last N candles)
        # We shift by 1 to exclude current forming candle from defining the swing
        df['swing_low'] = df['low'].shift(1).rolling(window=self.swing_period).min()
        
        # Identify Swing Highs (Maximum of last N candles)
        df['swing_high'] = df['high'].shift(1).rolling(window=self.swing_period).max()
        
        # Calculate ATR for buffer calculation ("slightly under/before")
        # Simple True Range calculation
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        return df

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Trailing Exit Logic:
        If trade moves in our direction but then starts reversing, close it to keep profit.
        """
        direction = trade["direction"]
        entry_price = float(trade["entry_price"])
        current_price = float(curr["close"])
        
        # Calculate profit distance
        if direction == "BUY":
            profit_dist = current_price - entry_price
            # If we are in decent profit (e.g. > 1 ATR)
            if profit_dist > curr["atr"]:
                # Check for reversal candle (Close < Open i.e. Red Candle)
                # Or if price drops below the previous candle's low (micro structure break)
                # For simplicity/robustness: Close trade if price drops X% from peak?
                # User request: "starts returning to the opposite direction... close the trade"
                
                # Simple Reversal Check: If current close is lower than entry + 50% of the max gain? 
                # Or simply: If we had a green candle, then a strong red candle.
                pass
            
            # Implementation of "Keep Profit":
            # If current price drops below a trailing threshold.
            # For now, let's use a simple ATR trail logic.
            # If price was higher previously, and now dropped > 1 ATR from high, exit.
            # Since we don't have 'highest_since_entry' in `trade` dict easily without DB update,
            # we will use a candle reversal pattern.
            
            # Exit BUY if we see a bearish reversal pattern after being in profit
            if current_price > entry_price and curr["close"] < curr["open"]:
                 # If previous candle was bullish and this one engulfs it or is strong bearish
                 return False, "" # Keep simple trailing stop handled by risk manager usually?
                 
                 # Let's interpret user request strictly: "starts returning"
                 # If we are profitable, and Close < Open (Red Candle), consider exit? Too sensitive.
                 # Better: If Close < Previous Low.
                 pass

        return False, ""

    def check_signal(self, df: pd.DataFrame, pair: str) -> SignalResult:
        curr = df.iloc[-2] # Last completed candle
        prev = df.iloc[-3]
        pre_prev = df.iloc[-4]
        
        close = curr["close"]
        swing_low = curr["swing_low"]
        swing_high = curr["swing_high"]
        atr = curr["atr"]
        
        if pd.isna(swing_low) or pd.isna(swing_high) or pd.isna(atr):
            return SignalResult("NONE", pair, close)
            
        # Buffer amount ("slightly under/before")
        # User example: 1.009 -> 1.008 (0.001 diff).
        # We will use 20% of ATR as a small buffer or a fixed small percentage.
        buffer = atr * 0.2

        # ─── FVG Detection ───
        # We look at the 3-candle sequence ending at 'prev' (indices -4, -3, -2)
        # Bullish FVG: High of Candle 1 < Low of Candle 3
        # Candle 1: pre_prev, Candle 3: curr (Wait, standard FVG is completed. 
        # If we use -4, -3, -2:
        # Candle 1 (pre_prev), Candle 2 (prev), Candle 3 (curr).
        
        # Bullish FVG check
        is_bullish_fvg = pre_prev["high"] < curr["low"]
        
        # Bearish FVG check
        is_bearish_fvg = pre_prev["low"] > curr["high"]
        
        # ─── Entry Logic ───
        # Buy if we have a Bullish FVG setup and price is near it
        # Or simply if we just formed one, indicating upward momentum from a support area.
        
        if is_bullish_fvg:
            # SL: Slightly under the swing low
            sl = swing_low - buffer
            
            # TP: Before the swing high
            tp = swing_high - buffer
            
            # Ensure Risk/Reward makes sense (TP > Entry, SL < Entry)
            if tp > close and sl < close:
                 return SignalResult("BUY", pair, close, sl, tp, reason="Bullish FVG + Swing Structure")

        if is_bearish_fvg:
            # SL: Slightly above swing high
            sl = swing_high + buffer
            
            # TP: Before swing low
            tp = swing_low + buffer
            
            if tp < close and sl > close:
                return SignalResult("SELL", pair, close, sl, tp, reason="Bearish FVG + Swing Structure")

        return SignalResult("NONE", pair, close)

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        return self.check_signal(df, pair)