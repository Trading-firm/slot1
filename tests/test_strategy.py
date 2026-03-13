"""
tests/test_strategy.py
───────────────────────
Unit tests for the EMA+RSI strategy and risk manager.
Run with: pytest tests/ -v
"""

import pytest
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.ema_rsi import EMARSIStrategy, SignalResult
from config.settings import settings


# ─── Fixtures ─────────────────────────────────────────────
def make_candles(n=100, trend="up") -> pd.DataFrame:
    """Generate synthetic OHLCV candles for testing."""
    np.random.seed(42)
    base  = 1.1000
    close = [base]

    for i in range(1, n):
        if trend == "up":
            change = np.random.normal(0.0003, 0.0010)
        elif trend == "down":
            change = np.random.normal(-0.0003, 0.0010)
        else:
            change = np.random.normal(0, 0.0010)
        close.append(max(0.5, close[-1] + change))

    close  = np.array(close)
    high   = close + np.abs(np.random.normal(0, 0.0005, n))
    low    = close - np.abs(np.random.normal(0, 0.0005, n))
    open_  = close + np.random.normal(0, 0.0003, n)
    volume = np.random.randint(1000, 10000, n).astype(float)

    index = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open":   open_,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": volume,
    }, index=index)


# ─── Strategy Tests ───────────────────────────────────────
class TestEMARSIStrategy:

    def setup_method(self):
        self.strategy = EMARSIStrategy()

    def test_indicators_calculated(self):
        df = make_candles(100)
        df = self.strategy.calculate_indicators(df)
        assert "ema_fast"     in df.columns
        assert "ema_slow"     in df.columns
        assert "rsi"          in df.columns
        assert "atr"          in df.columns
        assert "bullish_cross"in df.columns
        assert "bearish_cross"in df.columns

    def test_no_nan_in_indicators(self):
        df = make_candles(100)
        df = self.strategy.calculate_indicators(df)
        assert not df["ema_fast"].isna().any()
        assert not df["ema_slow"].isna().any()
        assert not df["rsi"].isna().any()

    def test_rsi_range(self):
        df = make_candles(100)
        df = self.strategy.calculate_indicators(df)
        assert (df["rsi"] >= 0).all()
        assert (df["rsi"] <= 100).all()

    def test_analyse_returns_signal_result(self):
        df     = make_candles(100)
        result = self.strategy.analyse(df, "EUR/USD")
        assert isinstance(result, SignalResult)
        assert result.signal in ["BUY", "SELL", "NONE"]
        assert result.pair == "EUR/USD"

    def test_analyse_too_few_candles(self):
        df     = make_candles(10)  # Not enough candles
        result = self.strategy.analyse(df, "EUR/USD")
        assert result.signal == "NONE"

    def test_buy_signal_has_sl_tp(self):
        df     = make_candles(150, trend="up")
        result = self.strategy.analyse(df, "EUR/USD")
        if result.signal == "BUY":
            assert result.stop_loss   is not None
            assert result.take_profit is not None
            assert result.stop_loss   < result.close
            assert result.take_profit > result.close

    def test_sell_signal_has_sl_tp(self):
        df     = make_candles(150, trend="down")
        result = self.strategy.analyse(df, "EUR/USD")
        if result.signal == "SELL":
            assert result.stop_loss   is not None
            assert result.take_profit is not None
            assert result.stop_loss   > result.close
            assert result.take_profit < result.close

    # def test_tp_sl_ratio_is_2_to_1(self):
    #     """
    #     Legacy Test: Removed because we now use dynamic TP (0.5%-2%) 
    #     which may be smaller than fixed SL (1%) for faster exits.
    #     """
    #     pass

    def test_summary_returns_dict(self):
        df      = make_candles(100)
        summary = self.strategy.get_summary(df)
        assert isinstance(summary, dict)
        assert "close"    in summary
        assert "ema_fast" in summary
        assert "rsi"      in summary


# ─── Settings Tests ───────────────────────────────────────
class TestSettings:

    def test_ema_fast_less_than_slow(self):
        assert settings.EMA_FAST < settings.EMA_SLOW, \
            "EMA fast period must be less than EMA slow period"

    # def test_tp_greater_than_sl_multiplier(self):
    #     """Legacy Test: Removed (Fixed SL % vs Dynamic TP)"""
    #     pass

    def test_risk_per_trade_reasonable(self):
        assert 0 < settings.RISK_PER_TRADE <= 0.05, \
            "Risk per trade should be between 0% and 5%"

    def test_max_daily_loss_reasonable(self):
        assert 0 < settings.MAX_DAILY_LOSS <= 0.20, \
            "Max daily loss should be between 0% and 20%"
