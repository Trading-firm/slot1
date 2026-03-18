
import pandas as pd
import numpy as np
import ta
from dataclasses import dataclass
from typing import Optional
from config.settings import settings
from utils.logger import logger
from strategies.base_strategy import BaseStrategy

@dataclass
class SignalResult:
    signal: str
    pair: str
    close: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""

class CandlestickPatternStrategy(BaseStrategy):
    """
    Candlestick Pattern Strategy
    
    Detects:
    - Bullish/Bearish Engulfing
    - Hammer / Shooting Star
    - Doji (as confirmation)
    
    Filters:
    - EMA 200 Trend Filter (Trade with trend)
    - RSI Filter (Momentum/Safety)
    - ADX Filter (Trend Strength)
    """

    def __init__(self):
        self.ema_trend_period = settings.EMA_TREND_PERIOD
        self.rsi_period = settings.RSI_PERIOD
        self.adx_period = 14
        self.adx_threshold = settings.MIN_ADX_STRENGTH  # 20.0
        
        # Risk Management (Global Standard)
        self.sl_multiplier = settings.ATR_MULTIPLIER_SL  # 1.5
        self.tp_multiplier = settings.ATR_MULTIPLIER_TP  # 1.5 (1:1 Ratio)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 200:
            return df

        # Basic Indicators
        df["ema_trend"] = ta.trend.EMAIndicator(close=df["close"], window=self.ema_trend_period).ema_indicator()
        df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period).rsi()
        df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()
        df["adx"] = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=self.adx_period).adx()

        # Candle features
        df['body'] = df['close'] - df['open']
        df['abs_body'] = df['body'].abs()
        df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
        df['total_range'] = df['high'] - df['low']
        
        # Previous candle features
        df['prev_open'] = df['open'].shift(1)
        df['prev_close'] = df['close'].shift(1)
        df['prev_body'] = df['prev_close'] - df['prev_open']
        df['prev_abs_body'] = df['prev_body'].abs()
        
        return df

    def _check_engulfing(self, curr, prev):
        """
        Bullish Engulfing: Prev Red, Curr Green, Curr Body engulfs Prev Body
        Bearish Engulfing: Prev Green, Curr Red, Curr Body engulfs Prev Body
        """
        # Bullish
        if (prev['body'] < 0 and curr['body'] > 0 and 
            curr['close'] > prev['open'] and curr['open'] < prev['close']):
            return "BULLISH"
            
        # Bearish
        if (prev['body'] > 0 and curr['body'] < 0 and 
            curr['close'] < prev['open'] and curr['open'] > prev['close']):
            return "BEARISH"
            
        return "NONE"

    def _check_pinbar(self, row):
        """
        Hammer (Bullish): Long lower shadow, small body
        Shooting Star (Bearish): Long upper shadow, small body
        """
        body_size = row['abs_body']
        upper_shadow = row['upper_shadow']
        lower_shadow = row['lower_shadow']
        total_range = row['total_range']
        
        # Avoid Dojis (body too small relative to range, but larger than 0)
        if total_range == 0: return "NONE"
        
        # Hammer Logic: Lower shadow >= 2 * body, Upper shadow small
        if lower_shadow >= (2 * body_size) and upper_shadow <= (0.5 * body_size):
            return "HAMMER" # Bullish
            
        # Shooting Star Logic: Upper shadow >= 2 * body, Lower shadow small
        if upper_shadow >= (2 * body_size) and lower_shadow <= (0.5 * body_size):
            return "SHOOTING_STAR" # Bearish
            
        return "NONE"

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 205:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-1] # Current candle (closed) - Wait, usually we trade on close of candle, so -1 is the just completed candle? 
                           # In live trading, we usually look at -2 (completed) and -1 (forming). 
                           # But standard here seems to be: Engine calls this with historical data.
                           # If engine fetches current forming candle, we should look at -2 (last completed).
                           # Let's check other strategies. strategies/ema_rsi.py uses curr = df.iloc[-1].
                           # Assumption: df contains CLOSED candles. If engine fetches including current forming, we must be careful.
                           # MT5 fetch_ohlcv usually returns completed candles if we ask for history.
                           # However, standard practice is `curr = df.iloc[-1]` is the LATEST data point.
        
        # Checking `strategies/ema_rsi.py`... 
        # It calculates indicators on the whole DF.
        # `curr` is passed to check_signal? No, check_signal takes `curr`.
        # In `analyse`, it calls `check_signal(df.iloc[-1])`.
        # If `df.iloc[-1]` is the just completed candle, this is correct.
        
        # Update: Standardize on -2 (last completed) to be safe across all engines
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        
        close = curr["close"]
        atr = curr["atr"]
        rsi = curr["rsi"]
        adx = curr["adx"]
        ema_trend = curr["ema_trend"]
        
        # 1. Trend Filter
        uptrend = close > ema_trend
        downtrend = close < ema_trend
        
        # 2. ADX Filter (Strength)
        strong_trend = adx > self.adx_threshold
        
        # 3. RSI Filter
        rsi_buy_ok = rsi < 70
        rsi_sell_ok = rsi > 30
        
        # 4. Pattern Recognition
        engulfing = self._check_engulfing(curr, prev)
        pinbar = self._check_pinbar(curr)
        
        signal = "NONE"
        reason = ""
        
        # ─── BUY SIGNALS ─────────────────────────────────
        if uptrend and strong_trend and rsi_buy_ok:
            if engulfing == "BULLISH":
                signal = "BUY"
                reason = "Bullish Engulfing + Uptrend + ADX > 20"
            elif pinbar == "HAMMER":
                signal = "BUY"
                reason = "Hammer (Pinbar) + Uptrend + ADX > 20"
                
        # ─── SELL SIGNALS ────────────────────────────────
        if downtrend and strong_trend and rsi_sell_ok:
            if engulfing == "BEARISH":
                signal = "SELL"
                reason = "Bearish Engulfing + Downtrend + ADX > 20"
            elif pinbar == "SHOOTING_STAR":
                signal = "SELL"
                reason = "Shooting Star (Pinbar) + Downtrend + ADX > 20"

        if signal != "NONE":
            sl_mult, tp_mult = self._get_sl_tp_settings(pair)

            sl_dist = atr * sl_mult
            tp_dist = atr * tp_mult
            
            if signal == "BUY":
                sl = close - sl_dist
                tp = close + tp_dist
            else:
                sl = close + sl_dist
                tp = close - tp_dist
                
            return SignalResult(signal, pair, close, sl, tp, reason)
            
        return SignalResult("NONE", pair, close, reason="No pattern or filtered")

    def check_exit(self, curr: pd.Series, trade: dict) -> tuple:
        """
        Exit logic:
        1. Trend Reversal (Price crosses EMA 200)
        2. RSI Extreme Reversal (Bought and RSI > 80, Sold and RSI < 20)
        """
        direction = trade["direction"]
        close = curr["close"]
        ema_trend = curr["ema_trend"]
        rsi = curr["rsi"]
        
        if direction == "BUY":
            if close < ema_trend:
                return True, f"Trend Reversal (Price {close:.2f} < EMA {ema_trend:.2f})"
            if rsi > 80:
                return True, f"RSI Overbought ({rsi:.1f} > 80)"
                
        elif direction == "SELL":
            if close > ema_trend:
                return True, f"Trend Reversal (Price {close:.2f} > EMA {ema_trend:.2f})"
            if rsi < 20:
                return True, f"RSI Oversold ({rsi:.1f} < 20)"
                
        return False, ""
