
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Tuple
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
    psar: float = 0.0

class ParabolicSARStrategy(BaseStrategy):
    def __init__(self, step=0.02, max_step=0.2):
        self.step = step
        self.max_step = max_step
        self.atr_tp_mult = settings.ATR_MULTIPLIER_TP

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # EMA 200 for Trend Filtering
        ema_trend = ta.trend.EMAIndicator(close=df["close"], window=200)
        df["ema_trend"] = ema_trend.ema_indicator()
        
        # Parabolic SAR
        psar = ta.trend.PSARIndicator(high=df["high"], low=df["low"], close=df["close"], step=self.step, max_step=self.max_step)
        df["psar"] = psar.psar()
        
        # ATR (Volatility)
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
        close = float(curr["close"])
        psar = float(curr["psar"])
        atr = float(curr["atr"])
        ema_trend = float(curr["ema_trend"])
        rsi = float(curr["rsi"])
        adx = float(curr["adx"])
        
        prev_below = prev["close"] < prev["psar"]
        curr_above = curr["close"] > curr["psar"]
        
        # Get dynamic settings for this pair
        sl_mult, tp_mult = self._get_sl_tp_settings(pair)
        
        # Filter: ADX > 20 (Ensure Trend Strength)
        if adx < 20:
             return SignalResult("NONE", pair, close, reason=f"Weak Trend (ADX {adx:.1f} < 20)")

        # Bullish Flip
        # 1. PSAR flips below price
        # 2. Price is above EMA 200 (Uptrend)
        # 3. RSI is < 70 (Not Overbought)
        if prev_below and curr_above:
             if close < ema_trend:
                 return SignalResult("NONE", pair, close, reason=f"Against Trend (Price < EMA200)")
             
             if rsi > 70:
                 return SignalResult("NONE", pair, close, reason=f"Overbought (RSI {rsi:.1f})")

             sl_dist = atr * sl_mult
             tp_dist = atr * tp_mult
             
             sl = close - sl_dist
             tp = close + tp_dist
             return SignalResult("BUY", pair, close, sl, tp, reason="PSAR Flip Bullish + Trend Confirmed", psar=psar)
             
        prev_above = prev["close"] > prev["psar"]
        curr_below = curr["close"] < curr["psar"]
        
        # Bearish Flip
        # 1. PSAR flips above price
        # 2. Price is below EMA 200 (Downtrend)
        # 3. RSI is > 30 (Not Oversold)
        if prev_above and curr_below:
             if close > ema_trend:
                 return SignalResult("NONE", pair, close, reason=f"Against Trend (Price > EMA200)")
                 
             if rsi < 30:
                 return SignalResult("NONE", pair, close, reason=f"Oversold (RSI {rsi:.1f})")

             sl_dist = atr * sl_mult
             tp_dist = atr * tp_mult
             
             sl = close + sl_dist
             tp = close - tp_dist
             return SignalResult("SELL", pair, close, sl, tp, reason="PSAR Flip Bearish + Trend Confirmed", psar=psar)
             
        return SignalResult("NONE", pair, close, reason="No flip", psar=psar)

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Check if we should exit the trade early based on strategy logic.
        """
        direction = trade["direction"]
        close = float(curr["close"])
        psar = float(curr["psar"])
        
        # Exit Buy if Price crosses below PSAR
        if direction == "BUY":
            if close < psar:
                 return True, "Exit Signal: Price below PSAR"
                 
        # Exit Sell if Price crosses above PSAR
        elif direction == "SELL":
             if close > psar:
                 return True, "Exit Signal: Price above PSAR"
                 
        return False, ""

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        return self.check_signal(curr, prev, pair)
