
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Tuple
from config.settings import settings

@dataclass
class SignalResult:
    signal: str
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    cci: float = 0.0

class CCITrendStrategy:
    def __init__(self, period=20, threshold=100):
        self.period = period
        self.threshold = threshold
        self.atr_tp_mult = settings.ATR_MULTIPLIER_TP

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # CCI (Trend Strength)
        cci = ta.trend.CCIIndicator(high=df["high"], low=df["low"], close=df["close"], window=self.period)
        df["cci"] = cci.cci()
        
        # ATR (Volatility for SL/TP)
        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["atr"] = atr.average_true_range()
        
        # EMA 50 (Trend Direction Filter)
        ema = ta.trend.EMAIndicator(close=df["close"], window=50)
        df["ema"] = ema.ema_indicator()
        
        # RSI (Momentum Confirmation - Avoid overbought/oversold entries)
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=14)
        df["rsi"] = rsi.rsi()
        
        return df

    def _get_sl_tp_settings(self, pair: str):
        """
        Returns (sl_atr_mult, tp_atr_mult, sl_type) based on pair specific settings or global defaults.
        """
        sl_mult = settings.ATR_MULTIPLIER_SL
        tp_mult = settings.ATR_MULTIPLIER_TP
        
        if "Volatility 75" in pair or "Vol 75" in pair or "R_75" in pair:
            sl_mult = settings.VOL75_SL_ATR_MULT
            tp_mult = settings.VOL75_TP_ATR_MULT
        elif "Volatility 25" in pair or "Vol 25" in pair or "R_25" in pair:
            sl_mult = settings.VOL25_SL_ATR_MULT
            tp_mult = settings.VOL25_TP_ATR_MULT
        elif "Volatility 10" in pair or "Vol 10" in pair or "R_10" in pair:
            sl_mult = settings.VOL10_SL_ATR_MULT
            tp_mult = settings.VOL10_TP_ATR_MULT
            
        return sl_mult, tp_mult, "atr"

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        close = float(curr["close"])
        cci = float(curr["cci"])
        atr = float(curr["atr"])
        ema = float(curr["ema"])
        rsi = float(curr["rsi"])
        
        # Get dynamic settings for this pair
        sl_param, tp_param, sl_type = self._get_sl_tp_settings(pair)
        
        # ─── Filters ───
        # 1. Trend Filter (EMA 50)
        is_uptrend = close > ema
        is_downtrend = close < ema
        
        # 2. RSI Filter (Avoid entering at extremes)
        # Buy: RSI < 70 (Room to grow)
        # Sell: RSI > 30 (Room to fall)
        rsi_buy_ok = rsi < 70
        rsi_sell_ok = rsi > 30

        # ─── Signals ───
        
        # Bullish: CCI crosses above 100 AND Price > EMA 50
        # (Using strict crossover: prev < 100 and curr > 100)
        if prev["cci"] < self.threshold and cci > self.threshold and is_uptrend and rsi_buy_ok:
             sl_dist = atr * sl_param
             tp_dist = atr * tp_param
             
             sl = close - sl_dist
             tp = close + tp_dist
             return SignalResult("BUY", pair, close, sl, tp, reason=f"CCI > 100 + Uptrend (EMA) + RSI {rsi:.1f}", cci=cci)
             
        # Bearish: CCI crosses below -100 AND Price < EMA 50
        elif prev["cci"] > -self.threshold and cci < -self.threshold and is_downtrend and rsi_sell_ok:
             sl_dist = atr * sl_param
             tp_dist = atr * tp_param
             
             sl = close + sl_dist
             tp = close - tp_dist
             return SignalResult("SELL", pair, close, sl, tp, reason=f"CCI < -100 + Downtrend (EMA) + RSI {rsi:.1f}", cci=cci)
             
        return SignalResult("NONE", pair, close, reason="Range bound or Filtered", cci=cci)

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Check if we should exit the trade early based on strategy logic.
        """
        direction = trade["direction"]
        cci = float(curr["cci"])
        
        # Exit Buy if CCI falls back below 0 (Momentum lost)
        if direction == "BUY":
            if cci < 0:
                 return True, "Exit Signal: CCI Momentum Lost (< 0)"
                 
        # Exit Sell if CCI rises back above 0 (Momentum lost)
        elif direction == "SELL":
             if cci > 0:
                 return True, "Exit Signal: CCI Momentum Lost (> 0)"
                 
        return False, ""

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        return self.check_signal(curr, prev, pair)
