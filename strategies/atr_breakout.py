
import pandas as pd
import ta
from dataclasses import dataclass
from config.settings import settings
from typing import Tuple

@dataclass
class SignalResult:
    signal: str
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""

class ATRBreakoutStrategy:
    def __init__(self, atr_period=14, multiplier=2.0):
        self.atr_period = atr_period
        self.multiplier = multiplier

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # ATR for volatility
        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=self.atr_period)
        df["atr"] = atr.average_true_range()
        
        # EMA for Trend Filtering (EMA 50)
        ema = ta.trend.EMAIndicator(close=df["close"], window=50)
        df["ema"] = ema.ema_indicator()
        
        # RSI for Momentum/Overbought/Oversold Check
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=14)
        df["rsi"] = rsi.rsi()
        
        return df

    def _get_sl_tp_settings(self, pair: str) -> Tuple[float, float]:
        """
        Returns (sl_pct, tp_min_pct) based on asset class.
        """
        if "Vol" in pair or "Index" in pair:
            return settings.SL_PCT_INDICES, settings.TP_MIN_PCT_INDICES
        else:
            return settings.SL_PCT_FOREX, settings.TP_MIN_PCT_FOREX

    def _calculate_dynamic_tp(self, price: float, atr: float, tp_min_pct: float) -> float:
        """
        Calculate Dynamic TP distance based on ATR, clamped between min_pct and max_pct.
        """
        # Updated to use global ATR Multipliers (approx 1:1 risk/reward for small wins)
        raw_tp_dist = atr * settings.ATR_MULTIPLIER_TP
        min_tp_dist = price * tp_min_pct
        max_tp_dist = price * settings.TP_MAX_PCT
        return max(min_tp_dist, min(max_tp_dist, raw_tp_dist))

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Check if an open trade should be closed early based on reversal signals.
        Returns: (bool, str) -> (should_close, reason)
        """
        direction = trade["direction"]
        
        # 1. Trend Reversal Exit (Close crosses back over EMA)
        # If we are LONG, and price closes BELOW EMA, the trend might be over.
        if direction == "BUY" and curr["close"] < curr["ema"]:
            return True, "Price closed below EMA 50 (Trend Reversal)"
            
        # If we are SHORT, and price closes ABOVE EMA, the trend might be over.
        if direction == "SELL" and curr["close"] > curr["ema"]:
            return True, "Price closed above EMA 50 (Trend Reversal)"
            
        # 2. RSI Reversal Exit (Extreme Reversal)
        # If LONG and RSI goes > 80 (Extreme Overbought) then starts dropping, we might want to bank profit.
        # But for simplicity, let's just exit if RSI is extremely against us or exhausted.
        # Let's keep it simple: Trend Reversal is the main exit for Breakout strategies.
        
        return False, ""

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        upper_bound = prev["high"] + (prev["atr"] * self.multiplier)
        lower_bound = prev["low"] - (prev["atr"] * self.multiplier)
        
        # Get dynamic settings for this pair
        sl_pct, tp_min_pct = self._get_sl_tp_settings(pair)
        
        # ─── Trend & Momentum Filters ───
        # 1. Trend Filter: Only Buy above EMA 50, Sell below EMA 50
        is_uptrend = curr["close"] > curr["ema"]
        is_downtrend = curr["close"] < curr["ema"]
        
        # 2. RSI Filter: Avoid buying into resistance (Overbought) or selling into support (Oversold)
        # Allow room to run: Buy if RSI < 70, Sell if RSI > 30
        rsi_buy_ok = curr["rsi"] < 70
        rsi_sell_ok = curr["rsi"] > 30
        
        if curr["close"] > upper_bound and is_uptrend and rsi_buy_ok:
             # Calculate SL distance based on ATR (1.5x) or Fixed %?
             # Let's use ATR based SL for breakouts as volatility varies
             atr_sl = curr["atr"] * settings.ATR_MULTIPLIER_SL
             
             # Fallback to fixed % if ATR is weird, or take max
             fixed_sl = curr["close"] * sl_pct
             sl_dist = max(atr_sl, fixed_sl)
             
             # Dynamic TP
             tp_dist = self._calculate_dynamic_tp(curr["close"], curr["atr"], tp_min_pct)
             
             sl = curr["close"] - sl_dist
             tp = curr["close"] + tp_dist
             
             return SignalResult("BUY", pair, curr["close"], sl, tp, reason="ATR Breakout Upper + Trend Confirmed")
             
        elif curr["close"] < lower_bound and is_downtrend and rsi_sell_ok:
             # SL Calculation
             atr_sl = curr["atr"] * settings.ATR_MULTIPLIER_SL
             fixed_sl = curr["close"] * sl_pct
             sl_dist = max(atr_sl, fixed_sl)
             
             # TP Calculation
             tp_dist = self._calculate_dynamic_tp(curr["close"], curr["atr"], tp_min_pct)
             
             sl = curr["close"] + sl_dist
             tp = curr["close"] - tp_dist
             
             return SignalResult("SELL", pair, curr["close"], sl, tp, reason="ATR Breakout Lower + Trend Confirmed")
             
        return SignalResult("NONE", pair, curr["close"], reason="Range bound or Filtered")

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        return self.check_signal(curr, prev, pair)
