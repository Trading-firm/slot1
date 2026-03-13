"""
backtester/backtest.py
───────────────────────
Backtesting engine using backtrader.
Tests the EMA + RSI strategy against historical data
before running it with real/paper money.

Usage:
  python backtester/backtest.py --pair EUR/USD --timeframe 1h --days 180
"""

import argparse
import sys
import os
import matplotlib
matplotlib.use("Agg")   # Non-interactive backend — saves chart to file
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt
import backtrader.analyzers as btanalyzers
import pandas as pd

from broker.connector import ForexBroker
from config.settings import settings
from utils.logger import logger


# ─── Backtrader Strategies ──────────────────────────────────

class EMA_RSI_BT(bt.Strategy):
    """
    Backtrader implementation of the EMA Crossover + RSI strategy.
    Mirrors the live strategy logic exactly.
    """

    params = (
        ("ema_fast",    settings.EMA_FAST),
        ("ema_slow",    settings.EMA_SLOW),
        ("ema_trend",   settings.EMA_TREND_PERIOD),
        ("rsi_period",  settings.RSI_PERIOD),
        ("rsi_upper",   settings.RSI_UPPER),
        ("rsi_lower",   settings.RSI_LOWER),
        ("adx_period",  14),
        ("adx_threshold", settings.ADX_THRESHOLD),
        ("atr_period",  settings.ATR_PERIOD),
        ("sl_mult",     settings.STANDARD_SL_ATR),
        ("tp_mult",     settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct",    settings.RISK_PER_TRADE),
        ("trailing_stop", False),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.p.ema_fast)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.p.ema_slow)
        self.ema_trend= bt.indicators.EMA(self.data.close, period=self.p.ema_trend)
        
        self.rsi      = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr      = bt.indicators.ATR(self.data,       period=self.p.atr_period)
        self.adx      = bt.indicators.ADX(self.data,       period=self.p.adx_period)

        self.crossover = bt.indicators.CrossOver(self.ema_fast, self.ema_slow)

        self.order      = None
        self.stop_loss  = None
        self.take_profit= None
        self.trade_log  = []

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                "pnl":      round(trade.pnl, 4),
                "pnlcomm":  round(trade.pnlcomm, 4),
            })
            self.log(
                f"Trade closed | PnL: {trade.pnl:.4f} | Net: {trade.pnlcomm:.4f}"
            )

    def next(self):
        # Don't open a new trade if one is already open
        if self.position:
            # Check SL/TP manually
            price = self.data.close[0]
            
            # Trailing Stop Logic
            if self.p.trailing_stop:
                if self.position.size > 0:  # Long
                    # Trail SL if price moves in favor
                    if price > self.stop_loss + (self.atr[0] * 1.5):
                        new_sl = price - (self.atr[0] * 1.5)
                        if new_sl > self.stop_loss:
                            self.stop_loss = new_sl
                            self.log(f"Trailing SL moved to {self.stop_loss:.5f}")
                elif self.position.size < 0: # Short
                    if price < self.stop_loss - (self.atr[0] * 1.5):
                        new_sl = price + (self.atr[0] * 1.5)
                        if new_sl < self.stop_loss:
                            self.stop_loss = new_sl
                            self.log(f"Trailing SL moved to {self.stop_loss:.5f}")

            if self.stop_loss and self.take_profit:
                if self.position.size > 0:   # Long
                    if price <= self.stop_loss or price >= self.take_profit:
                        self.close()
                elif self.position.size < 0:  # Short
                    if price >= self.stop_loss or price <= self.take_profit:
                        self.close()
            return

        if self.order:
            return

        atr  = self.atr[0]
        adx  = self.adx[0]
        price= self.data.close[0]
        ema_trend = self.ema_trend[0]

        # ── BUY Signal ────────────────────────────────────
        # EMA Cross + RSI > 55 + Trend (Price > EMA200) + ADX > 25
        if (self.crossover[0] > 0 
            and self.rsi[0] > self.p.rsi_upper 
            and price > ema_trend
            and adx > self.p.adx_threshold):
            
            self.stop_loss   = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl  = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(
                    f"BUY signal | Price={price:.5f} | SL={self.stop_loss:.5f} | "
                    f"TP={self.take_profit:.5f} | RSI={self.rsi[0]:.2f} | ADX={adx:.2f}"
                )

        # ── SELL Signal ───────────────────────────────────
        # EMA Cross + RSI < 45 + Trend (Price < EMA200) + ADX > 25
        elif (self.crossover[0] < 0 
              and self.rsi[0] < self.p.rsi_lower
              and price < ema_trend
              and adx > self.p.adx_threshold):
            
            self.stop_loss   = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl  = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(
                    f"SELL signal | Price={price:.5f} | SL={self.stop_loss:.5f} | "
                    f"TP={self.take_profit:.5f} | RSI={self.rsi[0]:.2f} | ADX={adx:.2f}"
                )


class BollingerBreakout_BT(bt.Strategy):
    """
    Bollinger Band Breakout Strategy.
    captures explosive moves when price breaks outside the bands during expansion.
    """
    params = (
        ("window", 20),
        ("dev", 2.0),
        ("atr_period", 14),
        ("sl_mult", settings.STANDARD_SL_ATR),
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.p.window, devfactor=self.p.dev)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        
        # Bandwidth = (Upper - Lower) / Mid * 100
        self.bandwidth = (self.bb.top - self.bb.bot) / self.bb.mid * 100
        
        # Average Bandwidth (20-period SMA of bandwidth)
        self.avg_bandwidth = bt.indicators.SMA(self.bandwidth, period=20)
        
        self.order = None
        self.stop_loss = None
        self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            # Simple SL/TP check
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:   # Long
                    if price <= self.stop_loss or price >= self.take_profit:
                        self.close()
                elif self.position.size < 0:  # Short
                    if price >= self.stop_loss or price <= self.take_profit:
                        self.close()
            return

        if self.order:
            return

        price = self.data.close[0]
        upper = self.bb.top[0]
        lower = self.bb.bot[0]
        atr   = self.atr[0]
        
        # Expansion Check
        is_expanding = self.bandwidth[0] > self.avg_bandwidth[0]

        # BUY Signal: Price > Upper Band + Expansion
        if price > upper and is_expanding:
            self.stop_loss   = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            # Risk Management
            dist_sl  = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY Breakout | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        # SELL Signal: Price < Lower Band + Expansion
        elif price < lower and is_expanding:
            self.stop_loss   = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            # Risk Management
            dist_sl  = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL Breakout | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class MeanReversion_BT(bt.Strategy):
    """
    Mean Reversion Strategy (Bollinger + RSI).
    Best for ranging markets (Low ADX).
    """
    params = (
        ("window", 20),
        ("dev", 2.0),
        ("rsi_period", 14),
        ("rsi_lower", 30),
        ("rsi_upper", 70),
        ("adx_period", 14),
        ("adx_threshold", 25.0),
        ("sl_mult", settings.STANDARD_SL_ATR),
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.p.window, devfactor=self.p.dev)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.adx = bt.indicators.ADX(self.data, period=self.p.adx_period)
        self.atr = bt.indicators.ATR(self.data, period=14)
        
        self.order = None
        self.stop_loss = None
        self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            # Check SL/TP
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:   # Long
                    if price <= self.stop_loss or price >= self.take_profit:
                        self.close()
                elif self.position.size < 0:  # Short
                    if price >= self.stop_loss or price <= self.take_profit:
                        self.close()
            return

        if self.order:
            return

        price = self.data.close[0]
        upper = self.bb.top[0]
        lower = self.bb.bot[0]
        mid   = self.bb.mid[0]
        rsi   = self.rsi[0]
        adx   = self.adx[0]
        atr   = self.atr[0]

        # Filter: Only trade if ADX is low (Ranging market)
        if adx > self.p.adx_threshold:
            return

        # BUY Signal: Price <= Lower Band + RSI < Lower Threshold
        if price <= lower and rsi < self.p.rsi_lower:
            # Use Standard ATR SL/TP even for Mean Reversion to control risk
            self.stop_loss   = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl  = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY Reversion | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        # SELL Signal: Price >= Upper Band + RSI > Upper Threshold
        elif price >= upper and rsi > self.p.rsi_upper:
            self.stop_loss   = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl  = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL Reversion | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class MACDCross_BT(bt.Strategy):
    params = (
        ("fast", 12), ("slow", 26), ("signal", 9),
        ("atr_period", 14), 
        ("sl_mult", settings.STANDARD_SL_ATR), 
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.macd = bt.indicators.MACD(self.data.close, period_me1=self.p.fast, period_me2=self.p.slow, period_signal=self.p.signal)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        price = self.data.close[0]
        atr = self.atr[0]

        if self.crossover > 0: # Bullish
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY MACD | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        elif self.crossover < 0: # Bearish
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL MACD | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class Stochastic_BT(bt.Strategy):
    params = (
        ("k", 14), ("d", 3), ("smooth", 3),
        ("atr_period", 14), 
        ("sl_mult", settings.STANDARD_SL_ATR), 
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.stoch = bt.indicators.Stochastic(self.data, period=self.p.k, period_dfast=self.p.d, period_dslow=self.p.smooth)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        k = self.stoch.percK[0]
        k_prev = self.stoch.percK[-1]
        price = self.data.close[0]
        atr = self.atr[0]

        # Buy: Cross above 20
        if k_prev < 20 and k > 20:
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY Stoch | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        # Sell: Cross below 80
        elif k_prev > 80 and k < 80:
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL Stoch | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class ATRBreakout_BT(bt.Strategy):
    params = (
        ("atr_period", 14), ("multiplier", 2.0),
        ("sl_mult", settings.STANDARD_SL_ATR), 
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        # Need previous candle values for breakout level
        prev_high = self.data.high[-1]
        prev_low = self.data.low[-1]
        prev_atr = self.atr[-1]
        
        upper_bound = prev_high + (prev_atr * self.p.multiplier)
        lower_bound = prev_low - (prev_atr * self.p.multiplier)
        
        price = self.data.close[0]
        atr = self.atr[0]

        if price > upper_bound:
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY ATR Breakout | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        elif price < lower_bound:
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL ATR Breakout | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class SMACrossover_BT(bt.Strategy):
    params = (
        ("fast", 50), ("slow", 200),
        ("atr_period", 14), 
        ("sl_mult", settings.STANDARD_SL_ATR), 
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        price = self.data.close[0]
        atr = self.atr[0]

        if self.crossover > 0: # Golden Cross
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY SMA Cross | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        elif self.crossover < 0: # Death Cross
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL SMA Cross | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class CCITrend_BT(bt.Strategy):
    params = (
        ("period", 20), ("threshold", 100),
        ("atr_period", 14), 
        ("sl_mult", settings.STANDARD_SL_ATR), 
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.cci = bt.indicators.CCI(self.data, period=self.p.period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        cci = self.cci[0]
        cci_prev = self.cci[-1]
        price = self.data.close[0]
        atr = self.atr[0]

        # Buy: Cross above 100
        if cci_prev < self.p.threshold and cci > self.p.threshold:
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY CCI | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        # Sell: Cross below -100
        elif cci_prev > -self.p.threshold and cci < -self.p.threshold:
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL CCI | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class ParabolicSAR_BT(bt.Strategy):
    params = (
        ("af", 0.02), ("afmax", 0.2),
        ("atr_period", 14), 
        ("sl_mult", settings.STANDARD_SL_ATR),
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.psar = bt.indicators.PSAR(self.data, af=self.p.af, afmax=self.p.afmax) 
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        psar = self.psar[0]
        psar_prev = self.psar[-1]
        price = self.data.close[0]
        price_prev = self.data.close[-1]
        atr = self.atr[0]

        # Flip Bullish: Prev Close < Prev PSAR, Curr Close > Curr PSAR
        prev_below = price_prev < psar_prev
        curr_above = price > psar

        if prev_below and curr_above:
            # Standard ATR SL is safer than just PSAR
            # But PSAR strategy usually uses PSAR as SL. 
            # We will use PSAR as SL but clamp it with ATR if it's too far?
            # User wants standardized 1:2.
            # Let's use ATR based SL/TP to be consistent with request.
            # Or use PSAR as SL but ensure 1% risk.
            # User said "some strategize place the stop lost very far". PSAR can be far.
            # Let's use standardized ATR SL/TP for consistency.
            
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY PSAR | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        # Flip Bearish
        prev_above = price_prev > psar_prev
        curr_below = price < psar
        
        if prev_above and curr_below:
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL PSAR | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class RSIStoch_BT(bt.Strategy):
    params = (
        ("rsi_period", settings.RSI_PERIOD), ("k", 14), ("d", 3), ("smooth", 3),
        ("atr_period", settings.ATR_PERIOD),
        ("sl_mult", settings.STANDARD_SL_ATR), 
        ("tp_mult", settings.STANDARD_SL_ATR * settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )
    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.stoch = bt.indicators.Stochastic(self.data, period=self.p.k, period_dfast=self.p.d, period_dslow=self.p.smooth)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        rsi = self.rsi[0]
        k = self.stoch.percK[0]
        k_prev = self.stoch.percK[-1]
        price = self.data.close[0]
        atr = self.atr[0]

        # Buy: RSI > 50 and Stoch Cross Up 20
        if rsi > 50 and k_prev < 20 and k > 20:
            self.stop_loss = price - (atr * self.p.sl_mult)
            self.take_profit = price + (atr * self.p.tp_mult)
            
            dist_sl = price - self.stop_loss
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.buy(size=abs(size))
                self.log(f"BUY RSI+Stoch | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")

        # Sell: RSI < 50 and Stoch Cross Down 80
        elif rsi < 50 and k_prev > 80 and k < 80:
            self.stop_loss = price + (atr * self.p.sl_mult)
            self.take_profit = price - (atr * self.p.tp_mult)
            
            dist_sl = self.stop_loss - price
            if dist_sl > 0:
                size = (self.broker.getvalue() * self.p.risk_pct) / dist_sl
                self.order = self.sell(size=abs(size))
                self.log(f"SELL RSI+Stoch | Price={price:.5f} | SL={self.stop_loss:.5f} | TP={self.take_profit:.5f}")


class SupportResistance_BT(bt.Strategy):
    params = (
        ("window", 20),
        ("tolerance_pct", 0.001),
        ("risk_reward", settings.RISK_REWARD_RATIO),
        ("risk_pct", settings.RISK_PER_TRADE),
    )

    def __init__(self):
        # Support = Minimum Low of last N periods
        self.support = bt.indicators.Lowest(self.data.low, period=self.p.window)
        self.resistance = bt.indicators.Highest(self.data.high, period=self.p.window)
        self.order = None; self.stop_loss = None; self.take_profit = None

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status == order.Completed:
            direction = "BUY" if order.isbuy() else "SELL"
            self.log(f"{direction} executed @ {order.executed.price:.5f}")
        self.order = None

    def next(self):
        if self.position:
            price = self.data.close[0]
            if self.stop_loss and self.take_profit:
                if self.position.size > 0:
                    if price <= self.stop_loss or price >= self.take_profit: self.close()
                elif self.position.size < 0:
                    if price >= self.stop_loss or price <= self.take_profit: self.close()
            return

        if self.order: return

        price = self.data.close[0]
        # Use previous support/resistance to avoid lookahead (shift 1)
        support = self.support[-1]
        resistance = self.resistance[-1]
        
        # BUY at Support
        # Logic: Low touched Support area, but Close bounced up
        support = self.support[-1]
        resistance = self.resistance[-1]
        
        low = self.data.low[0]
        high = self.data.high[0]
        close = self.data.close[0]
        
        touched_support = low <= support * (1 + self.p.tolerance_pct)
        bounced_up = close > support
        
        touched_resistance = high >= resistance * (1 - self.p.tolerance_pct)
        bounced_down = close < resistance

        if touched_support and bounced_up:
             sl = support - (support * 0.001) # Small buffer below support
             tp_target = resistance
             
             risk = close - sl
             reward = tp_target - close
             
             if risk > 0 and (reward / risk) >= self.p.risk_reward:
                 size = (self.broker.getvalue() * self.p.risk_pct) / risk
                 self.order = self.buy(size=abs(size))
                 self.stop_loss = sl
                 self.take_profit = tp_target
                 self.log(f"BUY Support | Price={close:.5f} | SL={sl:.5f} | TP={tp_target:.5f}")

        # SELL at Resistance
        elif touched_resistance and bounced_down:
             sl = resistance + (resistance * 0.001) # Small buffer above resistance
             tp_target = support
             
             risk = sl - close
             reward = close - tp_target
             
             if risk > 0 and (reward / risk) >= self.p.risk_reward:
                 size = (self.broker.getvalue() * self.p.risk_pct) / risk
                 self.order = self.sell(size=abs(size))
                 self.stop_loss = sl
                 self.take_profit = tp_target
                 self.log(f"SELL Resistance | Price={close:.5f} | SL={sl:.5f} | TP={tp_target:.5f}")


# ─── Backtest Runner ──────────────────────────────────────
def run_backtest(pair: str, timeframe: str, starting_cash: float = 10000.0, strategy_name: str = "ema_rsi", df: pd.DataFrame = None, verbose: bool = True, **kwargs):
    """
    Run full backtest for the given pair.
    Fetches historical data, runs strategy, prints results.
    Returns:
        tuple: (profit_pct, win_rate, total_trades, drawdown)
    """
    if verbose:
        logger.info(f"Starting backtest | {pair} | {timeframe} | Strategy: {strategy_name} | Cash: ${starting_cash:,.2f}")

    # Strategy Selector
    strategies = {
        "ema_rsi": EMA_RSI_BT,
        "bollinger_breakout": BollingerBreakout_BT,
        "mean_reversion": MeanReversion_BT,
        "macd_cross": MACDCross_BT,
        "stochastic": Stochastic_BT,
        "atr_breakout": ATRBreakout_BT,
        "sma_crossover": SMACrossover_BT,
        "cci_trend": CCITrend_BT,
        "parabolic_sar": ParabolicSAR_BT,
        "rsi_stoch": RSIStoch_BT,
        "support_resistance": SupportResistance_BT
    }
    
    StrategyClass = strategies.get(strategy_name.lower())
    if not StrategyClass:
        logger.error(f"Unknown strategy: {strategy_name}. Available: {list(strategies.keys())}")
        return -100.0, 0.0, 0, 0.0

    # Fetch historical data
    if df is None or df.empty:
        try:
            broker_conn = ForexBroker()
            limit = 5000  # Try to fetch maximum available history
            df = broker_conn.fetch_ohlcv(pair=pair, timeframe=timeframe, limit=limit)
        except Exception as e:
            logger.error(f"Failed to fetch data for backtest of {pair}: {e}")
            return -100.0, 0.0, 0, 0.0 # Return huge loss on error

    if df.empty or len(df) < 100:
        logger.error("Not enough historical data for backtest.")
        return -100.0, 0.0, 0, 0.0

    logger.info(f"Data fetched: {len(df)} candles from {df.index[0]} to {df.index[-1]}")

    # Convert to backtrader data feed
    bt_data = bt.feeds.PandasData(
        dataname = df,
        datetime = None,   # Index is already datetime
        open     = "open",
        high     = "high",
        low      = "low",
        close    = "close",
        volume   = "volume",
        openinterest = -1,
    )

    # Setup cerebro
    cerebro = bt.Cerebro()
    cerebro.adddata(bt_data, name=pair)
    
    # Add strategy with optional kwargs overriding defaults
    cerebro.addstrategy(StrategyClass, **kwargs)
    logger.info(f"Selected Strategy: {strategy_name} (Params: {kwargs})")

    # Broker settings
    cerebro.broker.setcash(starting_cash)
    cerebro.broker.setcommission(commission=0.0001) # Standard forex commission roughly
    
    # Analyzers
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(btanalyzers.DrawDown,    _name="drawdown")
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name="trades")

    # Run
    results = cerebro.run()
    strat   = results[0]

    # Metrics
    final_value = cerebro.broker.getvalue()
    net_profit  = final_value - starting_cash
    profit_pct  = (net_profit / starting_cash) * 100.0
    
    # Get Analyzer Results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get("sharperatio", None)
    drawdown     = strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown", 0.0)
    trade_stats  = strat.analyzers.trades.get_analysis()

    total_trades = trade_stats.get("total", {}).get("closed", 0)
    won_trades   = trade_stats.get("won",   {}).get("total", 0)
    lost_trades  = trade_stats.get("lost",  {}).get("total", 0)
    win_rate     = (won_trades / total_trades * 100) if total_trades > 0 else 0.0

    if verbose:
        print(f"  {timeframe:3} | {strategy_name:20} | Profit: {profit_pct:6.2f}% | Win Rate: {win_rate:5.1f}% | Trades: {total_trades:3} | DD: {drawdown:6.2f}%")

    return profit_pct, win_rate, total_trades, drawdown


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run trading bot backtest")
    parser.add_argument("--pair",       default="EUR/USD", help="Forex pair e.g. EUR/USD")
    parser.add_argument("--timeframe",  default="1h",      help="Timeframe: 1m, 5m, 15m, 1h, 4h, 1d")
    parser.add_argument("--cash",       default=10000.0,   type=float, help="Starting cash")
    parser.add_argument("--strategy",   default="ema_rsi", help="Strategy: ema_rsi, bollinger_breakout, mean_reversion")
    parser.add_argument("--params",     default="",        help="Strategy params in format key=value,key2=value2")
    args = parser.parse_args()

    # Parse params string into dict
    strategy_params = {}
    if args.params:
        try:
            for item in args.params.split(","):
                key, value = item.split("=")
                # Try to convert to int or float
                try:
                    if "." in value:
                        value = float(value)
                    else:
                        value = int(value)
                except ValueError:
                    pass # Keep as string
                strategy_params[key] = value
        except Exception as e:
            logger.error(f"Failed to parse params: {e}")

    run_backtest(
        pair=args.pair, 
        timeframe=args.timeframe, 
        starting_cash=args.cash,
        strategy_name=args.strategy,
        **strategy_params
    )
