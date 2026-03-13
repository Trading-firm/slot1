
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
from datetime import datetime
import matplotlib.pyplot as plt
import sys
import os
import inspect

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.ema_rsi import EMARSIStrategy
from strategies.stochastic_oscillator import StochasticStrategy
from strategies.macd_cross import MACDCrossStrategy
from strategies.rsi_stoch import RSIStochStrategy
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.atr_breakout import ATRBreakoutStrategy
from strategies.bollinger_breakout import BollingerBreakoutStrategy
from strategies.cci_trend import CCITrendStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.parabolic_sar import ParabolicSARStrategy
from strategies.support_resistance import SupportResistanceStrategy

from config.settings import settings
from broker.mt5 import MT5Broker
from utils.logger import logger

# Disable logging during backtest to avoid clutter
# logger.setLevel("WARNING")

class BacktestEngine:
    def __init__(self, pair: str, initial_balance: float = 1000.0):
        self.pair = pair
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.trades: List[Dict] = []
        self.open_trades: List[Dict] = []
        self.equity_curve = []
        
        # Initialize strategies for ALL timeframes
        timeframes = ["15m", "30m", "1h", "4h"]
        self.strategies = {}
        
        # List of strategy classes to test
        strategy_classes = [
            ("ema_rsi", EMARSIStrategy),
            ("stochastic", StochasticStrategy),
            ("macd_cross", MACDCrossStrategy),
            ("rsi_stoch", RSIStochStrategy),
            ("sma_crossover", SMACrossoverStrategy),
            ("atr_breakout", ATRBreakoutStrategy),
            ("bollinger_breakout", BollingerBreakoutStrategy),
            ("cci_trend", CCITrendStrategy),
            ("mean_reversion", MeanReversionStrategy),
            ("parabolic_sar", ParabolicSARStrategy),
            ("support_resistance", SupportResistanceStrategy)
        ]

        for name, cls in strategy_classes:
            for tf in timeframes:
                key = f"{name}_{tf}"
                try:
                    self.strategies[key] = (cls(), tf)
                except Exception as e:
                    print(f"Failed to init {name}: {e}")
        
        self.data = {}  # Raw OHLCV
        self.processed_data = {} # Data with indicators

    def fetch_data(self, days: int = 60):
        """Fetch historical data from MT5 for all timeframes."""
        broker = MT5Broker()
        timeframes = ["15m", "30m", "1h", "4h"]
        minutes_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
        
        for tf in timeframes:
            limit = (24 * 60 // minutes_map[tf]) * days
            print(f"Fetching {limit} candles for {tf}...")
            try:
                self.data[tf] = broker.fetch_ohlcv(self.pair, tf, limit=limit)
            except Exception as e:
                print(f"Error fetching {tf}: {e}")
                self._generate_synthetic_data(days, tf)
        
        # Align data ranges to the shortest common period (limited by 15m usually)
        if "15m" in self.data and not self.data["15m"].empty:
            start_time = self.data["15m"].index[0]
            for tf in timeframes:
                if tf in self.data:
                    self.data[tf] = self.data[tf][self.data[tf].index >= start_time]
            print(f"Data fetched. Start: {start_time}")

    def _generate_synthetic_data(self, days, timeframe):
        print(f"Generating synthetic data for {timeframe}...")
        freq_map = {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}
        minutes_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
        
        periods = (24 * 60 // minutes_map[timeframe]) * days
        dates = pd.date_range(end=datetime.now(), periods=periods, freq=freq_map[timeframe])
        
        self.data[timeframe] = pd.DataFrame({
            "open": 1.1000, "high": 1.1050, "low": 1.0950, "close": 1.1020, "volume": 100
        }, index=dates)

    def pre_calculate_indicators(self):
        print("Pre-calculating indicators...")
        for name, (strategy, tf) in self.strategies.items():
            if tf not in self.data or self.data[tf].empty:
                print(f"Skipping {name}: No data for {tf}")
                continue
                
            df = self.data[tf].copy()
            try:
                # Calculate indicators on the full dataset
                processed_df = strategy.calculate_indicators(df)
                self.processed_data[name] = processed_df
            except Exception as e:
                print(f"Error pre-calculating for {name}: {e}")
                self.processed_data[name] = df # Fallback

    def run(self):
        """Run the backtest simulation using pre-calculated data."""
        self.pre_calculate_indicators()
        
        if "15m" not in self.data or self.data["15m"].empty:
            print("No 15m data available for simulation clock.")
            return

        df_15m = self.data["15m"]
        min_window = 205
        print("Running backtest simulation...")
        
        # Pre-compute index sets for faster lookup
        indices = {
            "30m": set(self.data["30m"].index) if "30m" in self.data else set(),
            "1h": set(self.data["1h"].index) if "1h" in self.data else set(),
            "4h": set(self.data["4h"].index) if "4h" in self.data else set()
        }
        
        # Lookup maps for index position
        idx_maps = {
            "30m": {t: i for i, t in enumerate(self.data["30m"].index)} if "30m" in self.data else {},
            "1h": {t: i for i, t in enumerate(self.data["1h"].index)} if "1h" in self.data else {},
            "4h": {t: i for i, t in enumerate(self.data["4h"].index)} if "4h" in self.data else {}
        }
        
        for i in range(min_window, len(df_15m)):
            current_time = df_15m.index[i]
            row = df_15m.iloc[i]
            
            # Check exit for ALL open trades (using 15m price for finest granularity)
            self._check_trades(current_time, row["close"], row["high"], row["low"], i)
            
            # Check entry for strategies
            # 15m
            self._run_strategies(i, "15m", current_time)
            
            # Higher timeframes
            for tf in ["30m", "1h", "4h"]:
                if current_time in indices[tf]:
                    idx = idx_maps[tf][current_time]
                    self._run_strategies(idx, tf, current_time)
            
            self.equity_curve.append({"time": current_time, "equity": self.balance})

    def _run_strategies(self, idx: int, timeframe: str, current_time):
        for name, (strategy, tf) in self.strategies.items():
            if tf != timeframe:
                continue
                
            try:
                df = self.processed_data[name]
                if idx >= len(df):
                    continue
                    
                curr = df.iloc[idx]
                prev = df.iloc[idx-1]
                
                # Check signal
                # Handle different signatures
                sig = inspect.signature(strategy.check_signal)
                if len(sig.parameters) == 2: # (curr, pair)
                    signal = strategy.check_signal(curr, self.pair)
                else: # (curr, prev, pair)
                    signal = strategy.check_signal(curr, prev, self.pair)
                
                if signal.signal in ["BUY", "SELL"]:
                    existing = [t for t in self.open_trades if t["strategy"] == name]
                    if not existing:
                        self._open_trade(signal, name, timeframe, current_time)
            except Exception as e:
                # print(f"Error in {name}: {e}")
                pass

    def _open_trade(self, signal, strategy_name, timeframe, current_time):
        risk_amt = self.balance * settings.RISK_PER_TRADE
        sl_dist = abs(signal.close - signal.stop_loss)
        
        if sl_dist == 0:
            return

        contract_size = 100000
        volume = risk_amt / (contract_size * sl_dist)
        volume = max(0.01, round(volume, 2))
        
        trade = {
            "entry_time": current_time,
            "pair": signal.pair,
            "type": signal.signal,
            "entry_price": signal.close,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "volume": volume,
            "strategy": strategy_name,
            "timeframe": timeframe,
            "status": "OPEN"
        }
        self.open_trades.append(trade)

    def _check_trades(self, current_time, current_close, current_high, current_low, idx_15m):
        # We need access to 1h index for 1h strategies exit check
        idx_1h = None
        if current_time.minute == 0:
             try:
                 idx_1h = self.data["1h"].index.get_loc(current_time)
             except:
                 pass

        for trade in self.open_trades[:]:
            pnl = 0
            closed = False
            exit_reason = ""
            
            # SL/TP Check
            if trade["type"] == "BUY":
                if current_low <= trade["sl"]:
                    pnl = (trade["sl"] - trade["entry_price"]) * trade["volume"] * 100000
                    closed = True
                    exit_reason = "SL Hit"
                elif current_high >= trade["tp"]:
                    pnl = (trade["tp"] - trade["entry_price"]) * trade["volume"] * 100000
                    closed = True
                    exit_reason = "TP Hit"
            elif trade["type"] == "SELL":
                if current_high >= trade["sl"]:
                    pnl = (trade["entry_price"] - trade["sl"]) * trade["volume"] * 100000
                    closed = True
                    exit_reason = "SL Hit"
                elif current_low <= trade["tp"]:
                    pnl = (trade["entry_price"] - trade["tp"]) * trade["volume"] * 100000
                    closed = True
                    exit_reason = "TP Hit"
            
            # Early Exit Check
            if not closed and hasattr(self.strategies[trade["strategy"]][0], "check_exit"):
                strategy, tf = self.strategies[trade["strategy"]]
                
                # Get correct row
                curr_candle = None
                if tf == "15m":
                    curr_candle = self.processed_data[trade["strategy"]].iloc[idx_15m]
                elif tf == "1h" and idx_1h is not None:
                     # Only check 1h exit on hour close
                     curr_candle = self.processed_data[trade["strategy"]].iloc[idx_1h]
                
                if curr_candle is not None:
                    try:
                        trade_dict = {"direction": trade["type"]}
                        should_exit, reason = strategy.check_exit(curr_candle, trade_dict)
                        
                        if should_exit:
                            if trade["type"] == "BUY":
                                pnl = (current_close - trade["entry_price"]) * trade["volume"] * 100000
                            else:
                                pnl = (trade["entry_price"] - current_close) * trade["volume"] * 100000
                            closed = True
                            exit_reason = reason
                    except Exception as e:
                        pass

            if closed:
                self.balance += pnl
                trade["exit_time"] = current_time
                trade["exit_price"] = current_close
                trade["pnl"] = pnl
                trade["exit_reason"] = exit_reason
                trade["status"] = "CLOSED"
                self.trades.append(trade)
                self.open_trades.remove(trade)

    def report(self):
        print("\n" + "="*60)
        print(f"BACKTEST REPORT: {self.pair}")
        print("="*60)
        print(f"Initial Balance: ${self.initial_balance:.2f}")
        print(f"Final Balance:   ${self.balance:.2f}")
        print(f"Total Return:    {((self.balance - self.initial_balance)/self.initial_balance)*100:.2f}%")
        print(f"Total Trades:    {len(self.trades)}")
        
        if not self.trades:
            return

        wins = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        
        win_rate = len(wins) / len(self.trades) * 100 if self.trades else 0
        avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0
        avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0
        
        print(f"Win Rate:        {win_rate:.2f}%")
        print(f"Avg Win:         ${avg_win:.2f}")
        print(f"Avg Loss:        ${avg_loss:.2f}")
        profit_factor = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses and sum(t['pnl'] for t in losses) != 0 else float('inf')
        print(f"Profit Factor:   {profit_factor:.2f}")
        
        print("\nStrategy Performance:")
        strat_perf = {}
        for t in self.trades:
            s = t["strategy"]
            if s not in strat_perf:
                strat_perf[s] = {"count": 0, "pnl": 0, "wins": 0}
            strat_perf[s]["count"] += 1
            strat_perf[s]["pnl"] += t["pnl"]
            if t["pnl"] > 0:
                strat_perf[s]["wins"] += 1
        
        for s, p in strat_perf.items():
            wr = p["wins"] / p["count"] * 100
            print(f"  {s:<15} | Trades: {p['count']:<3} | Win Rate: {wr:5.1f}% | PnL: ${p['pnl']:.2f}")
            
        print("="*60)

if __name__ == "__main__":
    try:
        engine = BacktestEngine("EUR/USD")
        engine.fetch_data(days=60)
        engine.run()
        engine.report()
    except Exception as e:
        print(f"Backtest failed: {e}")
        import traceback
        traceback.print_exc()
