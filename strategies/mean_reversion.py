
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Tuple
from config.settings import settings
from strategies.base_strategy import BaseStrategy

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
    rsi: float = 0.0

class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy using Bollinger Bands + RSI.
    Works best in RANGING markets (low ADX).
    BUY when Price touches Lower Band + RSI < 30 (Oversold).
    SELL when Price touches Upper Band + RSI > 70 (Overbought).
    """

    def __init__(self, window: int = 20, dev: float = 2.0, rsi_period: int = 14, 
                 rsi_lower: float = 30.0, rsi_upper: float = 70.0, adx_threshold: float = 25.0):
        self.window = window
        self.dev = dev
        self.rsi_period = rsi_period
        self.rsi_lower = rsi_lower
        self.rsi_upper = rsi_upper
        self.adx_threshold = adx_threshold

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # Bollinger Bands
        bb = ta.volatility.BollingerBands(close=df["close"], window=self.window, window_dev=self.dev)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()
        
        # ATR (Volatility for SL/TP)
        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["atr"] = atr.average_true_range()
        
        # RSI
        rsi_ind = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period)
        df["rsi"] = rsi_ind.rsi()
        
        # ADX (Trend Strength) - Used to FILTER OUT trending markets
        adx_ind = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["adx"] = adx_ind.adx()
        
        return df

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        close = float(curr["close"])
        upper = float(curr["bb_upper"])
        lower = float(curr["bb_lower"])
        mid   = float(curr["bb_mid"])
        rsi   = float(curr["rsi"])
        adx   = float(curr["adx"])
        atr   = float(curr["atr"])

        # ── Filter: Ranging Market Check ──
        # ADX must be LOW (< 25) to confirm we are NOT in a strong trend.
        # Trading Mean Reversion against a strong trend is suicide.
        if adx > self.adx_threshold:
            return SignalResult(
                signal="NONE", pair=pair, close=close,
                bb_upper=upper, bb_lower=lower, rsi=rsi,
                reason=f"Trend too strong for Reversion (ADX {adx:.1f} > {self.adx_threshold})"
            )

        # Get dynamic settings for this pair
        sl_param, _ = self._get_sl_tp_settings(pair)
        
        sl_dist = atr * sl_param

        # ── BUY Signal (Oversold Bounce with Confirmation) ──────────────────
        # 1. Previous candle was outside or touching the lower band.
        # 2. Current candle closed back INSIDE the lower band.
        # 3. RSI confirms oversold condition.
        if prev["close"] <= prev["bb_lower"] and close > lower and rsi < self.rsi_lower:
            sl = close - sl_dist
            tp = mid # Target the mean
            
            # Sanity Check: TP must be profitable
            if tp <= close:
                return SignalResult("NONE", pair, close, reason=f"TP target {tp:.5f} is not above entry {close:.5f}")
            
            return SignalResult(
                signal="BUY", pair=pair, close=close,
                stop_loss=sl, take_profit=tp,
                bb_upper=upper, bb_lower=lower, rsi=rsi,
                reason=f"Confirmed bounce from Lower BB + RSI Oversold ({rsi:.1f} < {self.rsi_lower}) + Ranging (ADX {adx:.1f})"
            )

        # ── SELL Signal (Overbought Reversal with Confirmation) ─────────────
        # 1. Previous candle was outside or touching the upper band.
        # 2. Current candle closed back INSIDE the upper band.
        # 3. RSI confirms overbought condition.
        if prev["close"] >= prev["bb_upper"] and close < upper and rsi > self.rsi_upper:
            sl = close + sl_dist
            tp = mid # Target the mean

            # Sanity Check: TP must be profitable
            if tp >= close:
                return SignalResult("NONE", pair, close, reason=f"TP target {tp:.5f} is not below entry {close:.5f}")
            
            return SignalResult(
                signal="SELL", pair=pair, close=close,
                stop_loss=sl, take_profit=tp,
                bb_upper=upper, bb_lower=lower, rsi=rsi,
                reason=f"Confirmed rejection from Upper BB + RSI Overbought ({rsi:.1f} > {self.rsi_upper}) + Ranging (ADX {adx:.1f})"
            )

        return SignalResult(
            signal="NONE", pair=pair, close=close,
            bb_upper=upper, bb_lower=lower, rsi=rsi,
            reason=f"No confirmed reversion (RSI={rsi:.1f}, ADX={adx:.1f})"
        )

    def check_exit(self, curr: pd.Series, trade: dict) -> Tuple[bool, str]:
        """
        Early exit if market conditions change from Ranging to Trending.
        """
        adx = float(curr["adx"])
        
        # If ADX spikes, the ranging assumption is invalid. Exit the trade.
        # Using a slightly higher threshold for exit than for entry.
        exit_adx_threshold = self.adx_threshold + 5
        if adx > exit_adx_threshold:
             return True, f"Exit Signal: Market is now trending (ADX {adx:.1f} > {exit_adx_threshold})"
                 
        return False, ""

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")

        df = self.calculate_indicators(df)

        # Use the last COMPLETED candle (index -2) to avoid repainting
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        
        return self.check_signal(curr, prev, pair)
