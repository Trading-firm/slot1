
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

class RSIStochStrategy:
    """
    RSI + Stochastic Combination.
    Buy: RSI > 50 AND Stoch K crosses above 20
    Sell: RSI < 50 AND Stoch K crosses below 80
    """
    def __init__(self, rsi_period=14, stoch_k=14, stoch_d=3):
        self.rsi_period = rsi_period
        self.stoch_k = stoch_k
        self.stoch_d = stoch_d
        # Use global settings for SL/TP
        self.sl_pct = settings.SL_PCT
        self.tp_min_pct = settings.TP_MIN_PCT
        self.tp_max_pct = settings.TP_MAX_PCT
        self.atr_tp_mult = settings.ATR_MULTIPLIER_TP

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # EMA 200 for Trend Filtering
        ema_trend = ta.trend.EMAIndicator(close=df["close"], window=200)
        df["ema_trend"] = ema_trend.ema_indicator()

        # RSI
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period)
        df["rsi"] = rsi.rsi()

        # Stoch
        stoch = ta.momentum.StochasticOscillator(high=df["high"], low=df["low"], close=df["close"], window=self.stoch_k, smooth_window=3)
        df["stoch_k"] = stoch.stoch()
        
        # ATR
        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["atr"] = atr.average_true_range()
        
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
        rsi = float(curr["rsi"])

        # ── BUY Exit Logic ────────────────────────────────
        if direction == "BUY":
            # 1. Trend Reversal (Price closes below EMA 200)
            if close < ema_trend:
                return True, f"Early Exit: Trend Reversal (Price {close:.5f} < EMA200 {ema_trend:.5f})"
            
            # 2. Momentum Loss (RSI drops below 40)
            if rsi < 40:
                return True, f"Early Exit: Momentum Loss (RSI {rsi:.1f} < 40)"

        # ── SELL Exit Logic ───────────────────────────────
        elif direction == "SELL":
            # 1. Trend Reversal (Price closes above EMA 200)
            if close > ema_trend:
                return True, f"Early Exit: Trend Reversal (Price {close:.5f} > EMA200 {ema_trend:.5f})"
            
            # 2. Momentum Loss (RSI rises above 60)
            if rsi > 60:
                return True, f"Early Exit: Momentum Loss (RSI {rsi:.1f} > 60)"

        return False, ""

    def check_signal(self, curr: pd.Series, prev: pd.Series, pair: str) -> SignalResult:
        # Trend Filter: Only trade in direction of EMA 200
        uptrend = curr["close"] > curr["ema_trend"]
        downtrend = curr["close"] < curr["ema_trend"]
        
        adx = float(curr["adx"])
        
        # Default Settings
        min_adx = 20
        rsi_buy_min = 0
        rsi_buy_max = 70
        rsi_sell_min = 30
        rsi_sell_max = 100
        
        # Volatility 75 Specific Settings (Optimized)
        if "Volatility 75" in pair or "Vol 75" in pair or "R_75" in pair:
            min_adx = 25
            rsi_buy_min = 50  # Momentum Alignment (Buy Strength)
            rsi_buy_max = 70
            rsi_sell_min = 30
            rsi_sell_max = 50 # Momentum Alignment (Sell Weakness)
        
        # Filter: ADX (Ensure Trend Strength)
        if adx < min_adx:
             return SignalResult("NONE", pair, curr["close"], reason=f"Weak Trend (ADX {adx:.1f} < {min_adx})")

        # Bullish Signal (Buy Dip in Uptrend)
        # 1. Price is above EMA 200 (Uptrend)
        # 2. RSI is within allowed range
        # 3. Stoch K crosses ABOVE 20 (Exiting Oversold)
        rsi_bull = rsi_buy_min < curr["rsi"] < rsi_buy_max
        stoch_cross_up = prev["stoch_k"] < 20 and curr["stoch_k"] > 20
        
        if uptrend and rsi_bull and stoch_cross_up:
             sl_dist, tp_dist = self._calculate_sl_tp(curr["close"], curr["atr"], pair=pair)
             
             sl = curr["close"] - sl_dist
             tp = curr["close"] + tp_dist
             return SignalResult("BUY", pair, curr["close"], sl, tp, reason=f"Trend Up + Stoch Oversold Cross + ADX > {min_adx}")

        # Bearish Signal (Sell Rally in Downtrend)
        # 1. Price is below EMA 200 (Downtrend)
        # 2. RSI is within allowed range
        # 3. Stoch K crosses BELOW 80 (Exiting Overbought)
        rsi_bear = rsi_sell_min < curr["rsi"] < rsi_sell_max
        stoch_cross_down = prev["stoch_k"] > 80 and curr["stoch_k"] < 80
        
        if downtrend and rsi_bear and stoch_cross_down:
             sl_dist, tp_dist = self._calculate_sl_tp(curr["close"], curr["atr"], pair=pair)
             
             sl = curr["close"] + sl_dist
             tp = curr["close"] - tp_dist
             return SignalResult("SELL", pair, curr["close"], sl, tp, reason=f"Trend Down + Stoch Overbought Cross + ADX > {min_adx}")
             
        return SignalResult("NONE", pair, curr["close"], reason="No signal")

    def analyse(self, df: pd.DataFrame, pair: str) -> SignalResult:
        if len(df) < 50:
            return SignalResult("NONE", pair, 0.0, reason="Not enough data")
            
        df = self.calculate_indicators(df)
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        return self.check_signal(curr, prev, pair)
