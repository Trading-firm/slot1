
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

class StochasticStrategy:
    def __init__(self, k=14, d=3, smooth=3):
        self.k = k
        self.d = d
        self.smooth = smooth
        # Use global settings for SL/TP
        self.sl_pct = settings.SL_PCT
        self.tp_min_pct = settings.TP_MIN_PCT
        self.tp_max_pct = settings.TP_MAX_PCT
        self.atr_tp_mult = settings.ATR_MULTIPLIER_TP

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # EMA 200 for Trend Filtering
        ema_trend = ta.trend.EMAIndicator(close=df["close"], window=200)
        df["ema_trend"] = ema_trend.ema_indicator()

        stoch = ta.momentum.StochasticOscillator(
            high=df["high"], low=df["low"], close=df["close"], window=self.k, smooth_window=self.smooth
        )
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()
        
        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["atr"] = atr.average_true_range()
        
        # RSI (Momentum Confirmation)
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=14)
        df["rsi"] = rsi.rsi()

        # ADX (Trend Strength)
        adx = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["adx"] = adx.adx()
        
        return df

    def _get_sl_tp_multipliers(self, pair: str):
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
            
        return sl_mult, tp_mult

    def _calculate_sl_tp(self, price: float, atr: float, pair: str = "") -> tuple[float, float]:
        """
        Calculate SL and TP distances using standardized ATR settings.
        SL = 1.5 * ATR (High Probability)
        TP = 1.5 * ATR (1:1 Risk:Reward for Small Wins)
        """
        sl_mult, tp_mult = self._get_sl_tp_multipliers(pair)
        sl_dist = atr * sl_mult
        tp_dist = atr * tp_mult
        return sl_dist, tp_dist

    def check_exit(self, curr: pd.Series, trade: dict) -> tuple:
        """
        Check if an open trade should be closed early based on reversal signals.
        Returns: (bool, str) -> (should_close, reason)
        """
        direction = trade["direction"]
        close = float(curr["close"])
        ema_trend = float(curr["ema_trend"])
        stoch_k = float(curr["stoch_k"])
        stoch_d = float(curr["stoch_d"])
        rsi = float(curr["rsi"])

        # ── BUY Exit Logic ────────────────────────────────
        if direction == "BUY":
            # 1. Trend Reversal (Price closes below EMA 200)
            if close < ema_trend:
                return True, f"Early Exit: Trend Reversal (Price {close:.5f} < EMA200 {ema_trend:.5f})"
            
            # 2. Bearish Crossover in Overbought Zone
            if stoch_k > 80 and stoch_k < stoch_d:
                return True, f"Early Exit: Bearish Crossover in Overbought (K {stoch_k:.1f} < D {stoch_d:.1f})"

            # 3. Momentum Loss (RSI drops below 50)
            if rsi < 50:
                return True, f"Early Exit: Momentum Loss (RSI {rsi:.1f} < 50)"

        # ── SELL Exit Logic ───────────────────────────────
        elif direction == "SELL":
            # 1. Trend Reversal (Price closes above EMA 200)
            if close > ema_trend:
                return True, f"Early Exit: Trend Reversal (Price {close:.5f} > EMA200 {ema_trend:.5f})"
            
            # 2. Bullish Crossover in Oversold Zone
            if stoch_k < 20 and stoch_k > stoch_d:
                return True, f"Early Exit: Bullish Crossover in Oversold (K {stoch_k:.1f} > D {stoch_d:.1f})"

            # 3. Momentum Loss (RSI rises above 50)
            if rsi > 50:
                return True, f"Early Exit: Momentum Loss (RSI {rsi:.1f} > 50)"

        return False, ""

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        # Trend Filter: Only trade in direction of EMA 200
        uptrend = curr["close"] > curr["ema_trend"]
        downtrend = curr["close"] < curr["ema_trend"]

        stoch_k = float(curr["stoch_k"])
        stoch_d = float(curr["stoch_d"])
        prev_k = float(prev["stoch_k"])
        prev_d = float(prev["stoch_d"])
        
        adx = float(curr["adx"])
        rsi = float(curr["rsi"])
        
        # Filter: ADX > 20 (Ensure Trend Strength)
        if adx < 20:
             return SignalResult("NONE", pair, curr["close"], reason=f"Weak Trend (ADX {adx:.1f} < 20)")

        # Bullish: K crosses above D in Oversold (<20) + Uptrend
        # RSI must be < 70 (Not Overbought)
        bullish_cross = prev_k < prev_d and stoch_k > stoch_d and stoch_k < 80
        if uptrend and bullish_cross and stoch_k < 30: # Only enter if still relatively oversold
             if rsi > 70:
                 return SignalResult("NONE", pair, curr["close"], reason=f"Overbought (RSI {rsi:.1f})")

             sl_dist, tp_dist = self._calculate_sl_tp(curr["close"], curr["atr"], pair=pair)
            
             sl = curr["close"] - sl_dist
             tp = curr["close"] + tp_dist
             return SignalResult("BUY", pair, curr["close"], sl, tp, reason="Trend Up + Stoch Bullish Cross + ADX > 20")

        # Bearish: K crosses below D in Overbought (>80) + Downtrend
        # RSI must be > 30 (Not Oversold)
        bearish_cross = prev_k > prev_d and stoch_k < stoch_d and stoch_k > 20
        if downtrend and bearish_cross and stoch_k > 70: # Only enter if still relatively overbought
            if rsi < 30:
                return SignalResult("NONE", pair, curr["close"], reason=f"Oversold (RSI {rsi:.1f})")

            sl_dist, tp_dist = self._calculate_sl_tp(curr["close"], curr["atr"], pair=pair)
            
            sl = curr["close"] + sl_dist
            tp = curr["close"] - tp_dist
            return SignalResult("SELL", pair, curr["close"], sl, tp, reason="Trend Down + Stoch Bearish Cross + ADX > 20")
             
        return SignalResult("NONE", pair, curr["close"], reason="No signal")

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
