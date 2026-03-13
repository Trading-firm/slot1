
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Optional, Tuple
from config.settings import settings

@dataclass
class SignalResult:
    signal: str          # "BUY", "SELL", "NONE"
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_mid: float = 0.0
    bandwidth: float = 0.0

class BollingerBreakoutStrategy:
    """
    Bollinger Band Breakout Strategy.
    captures explosive moves when price breaks outside the bands during expansion.
    """

    def __init__(self, window: int = 20, dev: float = 2.0, atr_period: int = 14):
        self.window = window
        self.dev = dev
        self.atr_period = atr_period

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Bollinger Bands
        bb = ta.volatility.BollingerBands(close=df["close"], window=self.window, window_dev=self.dev)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()
        df["bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100
        
        # Bandwidth MA for expansion check
        df["avg_bandwidth"] = df["bandwidth"].rolling(window=20).mean()

        # ATR
        atr_ind = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=self.atr_period)
        df["atr"] = atr_ind.average_true_range()
        
        # RSI (Momentum Confirmation)
        rsi_ind = ta.momentum.RSIIndicator(close=df["close"], window=14)
        df["rsi"] = rsi_ind.rsi()
        
        # ADX (Trend Strength) - Only take breakouts if trend is strong
        adx_ind = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["adx"] = adx_ind.adx()
        
        return df

    def _calculate_sl_tp(self, price: float, atr: float) -> tuple[float, float]:
        """
        Calculate SL and TP distances using standardized ATR settings.
        SL = 1.5 * ATR (High Probability)
        TP = 1.5 * ATR (1:1 Risk:Reward for Small Wins)
        """
        sl_dist = atr * settings.ATR_MULTIPLIER_SL
        tp_dist = atr * settings.ATR_MULTIPLIER_TP # Use Global 1.5x setting
        return sl_dist, tp_dist

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        close = curr["close"]
        upper = curr["bb_upper"]
        lower = curr["bb_lower"]
        mid   = curr["bb_mid"]
        atr   = curr["atr"]
        bandwidth = curr["bandwidth"]
        avg_bandwidth = curr["avg_bandwidth"]
        rsi = curr["rsi"]
        adx = curr["adx"]
        
        # 1. Expansion Check: Bandwidth must be expanding (above average)
        is_expanding = bandwidth > avg_bandwidth
        
        # 2. ADX Check: Trend must be strong enough to sustain a breakout
        # ADX > 20 indicates a trend is forming/present.
        is_strong_trend = adx > 20
        
        # 3. RSI Check: Avoid entering if already overextended
        # Buy: RSI > 50 (Bullish momentum) but < 70 (Not overbought yet)
        # Sell: RSI < 50 (Bearish momentum) but > 30 (Not oversold yet)

        # ── BUY Signal ────────────────────────────────────
        # Price closes ABOVE Upper Band
        if close > upper and is_expanding and is_strong_trend:
            if 50 < rsi < 75: # Valid momentum range
                sl_dist, tp_dist = self._calculate_sl_tp(close, atr)
                
                sl = round(close - sl_dist, 5) 
                tp = round(close + tp_dist, 5)
                
                return SignalResult(
                    signal="BUY",
                    pair=pair,
                    close=close,
                    stop_loss=sl,
                    take_profit=tp,
                    bb_upper=upper,
                    bb_lower=lower,
                    bb_mid=mid,
                    bandwidth=bandwidth,
                    reason=f"BB Breakout Upper + ADX {adx:.1f} + RSI {rsi:.1f}"
                )

        # ── SELL Signal ───────────────────────────────────
        # Price closes BELOW Lower Band
        if close < lower and is_expanding and is_strong_trend:
             if 25 < rsi < 50: # Valid momentum range
                sl_dist, tp_dist = self._calculate_sl_tp(close, atr)
                
                sl = round(close + sl_dist, 5) 
                tp = round(close - tp_dist, 5)
                
                return SignalResult(
                    signal="SELL",
                    pair=pair,
                    close=close,
                    stop_loss=sl,
                    take_profit=tp,
                    bb_upper=upper,
                    bb_lower=lower,
                    bb_mid=mid,
                    bandwidth=bandwidth,
                    reason=f"BB Breakout Lower + ADX {adx:.1f} + RSI {rsi:.1f}"
                )

        return SignalResult(
            signal="NONE",
            pair=pair,
            close=close
        )

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Check if we should exit the trade early based on strategy logic.
        """
        direction = trade["direction"]
        close = float(curr["close"])
        mid = float(curr["bb_mid"])
        
        # Exit Buy if Price falls back below Middle Band (Trend Lost)
        if direction == "BUY":
            if close < mid:
                 return True, "Exit Signal: Price closed below Middle Band (Trend Lost)"
                 
        # Exit Sell if Price rises back above Middle Band (Trend Lost)
        elif direction == "SELL":
             if close > mid:
                 return True, "Exit Signal: Price closed above Middle Band (Trend Lost)"
                 
        return False, ""

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        return self.check_signal(curr, prev, pair)
