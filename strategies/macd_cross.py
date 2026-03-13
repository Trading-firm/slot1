
import pandas as pd
import ta
from dataclasses import dataclass
from config.settings import settings

@dataclass
class SignalResult:
    signal: str
    pair: str
    close: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""

class MACDCrossStrategy:
    def __init__(self, fast=12, slow=26, signal=9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        # Use global settings for SL/TP
        self.sl_pct = settings.SL_PCT
        self.tp_min_pct = settings.TP_MIN_PCT
        self.tp_max_pct = settings.TP_MAX_PCT
        self.atr_tp_mult = settings.ATR_MULTIPLIER_TP

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # EMA 200 for Trend Filtering
        ema_trend = ta.trend.EMAIndicator(close=df["close"], window=200)
        df["ema_trend"] = ema_trend.ema_indicator()

        # MACD
        macd = ta.trend.MACD(close=df["close"], window_slow=self.slow, window_fast=self.fast, window_sign=self.signal)
        df["macd"] = macd.macd()
        df["signal_line"] = macd.macd_signal()
        
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

    def _get_sl_tp_settings(self, pair: str):
        """
        Returns (sl_atr_mult, tp_atr_mult, sl_type) based on pair specific settings or global defaults.
        """
        # Default Global Settings
        sl_mult = settings.ATR_MULTIPLIER_SL
        tp_mult = settings.ATR_MULTIPLIER_TP
        
        # Asset Specific Overrides
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

    def _calculate_dynamic_tp(self, price: float, atr: float, tp_min_pct: float) -> float:
        """
        Deprecated: Using standardized ATR-based TP.
        """
        return atr * settings.ATR_MULTIPLIER_TP

    def check_exit(self, curr: pd.Series, trade: dict) -> tuple:
        """
        Check if an open trade should be closed early based on reversal signals.
        Returns: (bool, str) -> (should_close, reason)
        """
        direction = trade["direction"]
        close = float(curr["close"])
        ema_trend = float(curr["ema_trend"])
        macd = float(curr["macd"])
        signal_line = float(curr["signal_line"])
        rsi = float(curr["rsi"])

        # ── BUY Exit Logic ────────────────────────────────
        if direction == "BUY":
            # 1. Trend Reversal (Price closes below EMA 200)
            if close < ema_trend:
                return True, f"Early Exit: Trend Reversal (Price {close:.5f} < EMA200 {ema_trend:.5f})"
            
            # 2. Bearish Crossover (MACD crosses below Signal)
            if macd < signal_line:
                return True, f"Early Exit: Bearish Crossover (MACD {macd:.5f} < Signal {signal_line:.5f})"

            # 3. RSI Reversal (Momentum Loss)
            if rsi < 50:
                return True, f"Early Exit: RSI Momentum Loss ({rsi:.1f} < 50)"

        # ── SELL Exit Logic ───────────────────────────────
        elif direction == "SELL":
            # 1. Trend Reversal (Price closes above EMA 200)
            if close > ema_trend:
                return True, f"Early Exit: Trend Reversal (Price {close:.5f} > EMA200 {ema_trend:.5f})"
            
            # 2. Bullish Crossover (MACD crosses above Signal)
            if macd > signal_line:
                return True, f"Early Exit: Bullish Crossover (MACD {macd:.5f} > Signal {signal_line:.5f})"

            # 3. RSI Reversal (Momentum Loss)
            if rsi > 50:
                return True, f"Early Exit: RSI Momentum Loss ({rsi:.1f} > 50)"

        return False, ""

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        close = float(curr["close"])
        atr = float(curr["atr"])
        adx = float(curr["adx"])
        rsi = float(curr["rsi"])

        # Trend Filter: Only trade in direction of EMA 200
        uptrend = close > curr["ema_trend"]
        downtrend = close < curr["ema_trend"]

        # Strength Filter: ADX > 20 (Avoid flat markets)
        is_strong_trend = adx > 20

        # Momentum Filter: RSI Safety Zones
        rsi_buy_ok = rsi < 70
        rsi_sell_ok = rsi > 30

        # Get dynamic settings for this pair
        sl_param, tp_param, sl_type = self._get_sl_tp_settings(pair)

        if sl_type == "atr":
            sl_dist = atr * sl_param
            tp_dist = atr * tp_param
        else:
            sl_dist = close * sl_param
            tp_dist = self._calculate_dynamic_tp(close, atr, tp_param)

        # Buy: Bullish Crossover + Uptrend + ADX + RSI Safety
        if uptrend and prev["macd"] < prev["signal_line"] and curr["macd"] > curr["signal_line"] and is_strong_trend and rsi_buy_ok:
            sl = close - sl_dist
            tp = close + tp_dist
            return SignalResult("BUY", pair, close, sl, tp, reason=f"Trend Up + MACD Bull Cross + ADX {adx:.1f} + RSI {rsi:.1f}")
            
        # Sell: Bearish Crossover + Downtrend + ADX + RSI Safety
        elif downtrend and prev["macd"] > prev["signal_line"] and curr["macd"] < curr["signal_line"] and is_strong_trend and rsi_sell_ok:
            sl = close + sl_dist
            tp = close - tp_dist
            return SignalResult("SELL", pair, close, sl, tp, reason=f"Trend Down + MACD Bear Cross + ADX {adx:.1f} + RSI {rsi:.1f}")
            
        return SignalResult("NONE", pair, close, reason="No crossover or filtered")

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]

        # Minimum Volatility Filter
        # Avoid trading in flat markets where spread > profit potential
        # Threshold: ATR must be at least 0.05% of price
        min_atr_pct = 0.0005 
        if curr["atr"] < (curr["close"] * min_atr_pct):
            return SignalResult("NONE", pair, curr["close"], reason=f"Low Volatility (ATR {curr['atr']:.5f} < {min_atr_pct*100}%)")

        return self.check_signal(curr, prev, pair)
