import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta
import sys
from datetime import datetime
from dotenv import load_dotenv

# Import Strategies
from strategies.macd_cross import MACDCrossStrategy
from strategies.cci_trend import CCITrendStrategy
from strategies.rsi_stoch import RSIStochStrategy
from strategies.stochastic_oscillator import StochasticStrategy
from strategies.parabolic_sar import ParabolicSARStrategy
from strategies.support_resistance import SupportResistanceStrategy
from strategies.candlestick_pattern import CandlestickPatternStrategy
from strategies.atr_breakout import ATRBreakoutStrategy
from strategies.bollinger_breakout import BollingerBreakoutStrategy
from strategies.ema_rsi import EMARSIStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.fvg_strategy import FVGStrategy

class Backtester:
    def __init__(self, symbol, timeframe, timeframe_name="1h"):
        self.symbol = symbol
        self.timeframe = timeframe
        self.timeframe_name = timeframe_name
        self.strategies = self._init_strategies()
        self.df = None

    def _init_strategies(self):
        """Initialize all available strategies."""
        return {
            "MACD Cross": MACDCrossStrategy(),
            "CCI Trend": CCITrendStrategy(),
            "RSI + Stoch": RSIStochStrategy(),
            "Stochastic": StochasticStrategy(),
            "Parabolic SAR": ParabolicSARStrategy(),
            "Support & Resistance": SupportResistanceStrategy(tolerance_pct=0.005),
            "Candlestick Pattern": CandlestickPatternStrategy(),
            "ATR Breakout": ATRBreakoutStrategy(),
            "Bollinger Breakout": BollingerBreakoutStrategy(),
            "EMA + RSI": EMARSIStrategy(),
            "Mean Reversion": MeanReversionStrategy(),
            "SMA Crossover": SMACrossoverStrategy(),
            "FVG": FVGStrategy()
        }

    def get_data(self, n=5000):
        """Fetch historical data from MT5."""
        if not mt5.initialize():
            print(f"MT5 Init Failed: {mt5.last_error()}", flush=True)
            return False

        # Try different symbol names/aliases
        symbols_to_try = [
            self.symbol, 
            self.symbol.replace("Volatility", "Vol"), 
            self.symbol.replace("Volatility ", "R_"),
            "R_" + self.symbol.split(" ")[1] if "Volatility" in self.symbol and len(self.symbol.split(" ")) > 1 else self.symbol
        ]
        
        # Add common Forex aliases
        if "EUR" in self.symbol: symbols_to_try.extend(["EURUSD", "EURUSD.m", "EURUSD.pro"])
        
        rates = None
        used_symbol = None
        for sym in symbols_to_try:
            rates = mt5.copy_rates_from_pos(sym, self.timeframe, 0, n)
            if rates is not None and len(rates) > 0:
                used_symbol = sym
                break
        
        if rates is None:
            print(f"Failed to get data for {self.symbol} (tried {symbols_to_try})")
            return False

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Calculate global ATR (useful for reference/logging, strategies calculate their own)
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        
        self.df = df
        print(f"Data loaded for {used_symbol}: {len(df)} candles")
        return True

    def run(self):
        """Execute the backtest loop."""
        if self.df is None:
            if not self.get_data():
                return

        print(f"\n--- Running Backtest for {self.symbol} on {self.timeframe_name} ---")
        
        results = {}
        for name in self.strategies:
            results[name] = {"wins": 0, "losses": 0, "trades": [], "skip_until": 0}

        df = self.df
        # Start index (need enough history for indicators like EMA200)
        start_idx = 300 
        
        for i in range(start_idx, len(df)):
            if i % 1000 == 0:
                print(f"Processing candle {i}/{len(df)}...", end='\r')

            # Create a sliding window slice for the strategy
            # Strategies assume the last row in the df is the candle to analyse
            window_start = max(0, i - 300)
            current_slice = df.iloc[window_start:i+1].copy()

            for name, strategy in self.strategies.items():
                # Skip if currently in a trade
                if i < results[name]["skip_until"]:
                    continue

                try:
                    res = strategy.analyse(current_slice, self.symbol)
                    
                    if res.signal in ["BUY", "SELL"]:
                        entry_price = res.close
                        sl = res.stop_loss
                        tp = res.take_profit
                        
                        if sl == 0.0 or tp == 0.0:
                            continue

                        # Simulate Trade Outcome
                        outcome = "OPEN"
                        pnl = 0.0
                        exit_idx = i
                        
                        tp_dist = abs(tp - entry_price)
                        sl_dist = abs(sl - entry_price)

                        # Look forward in data to find exit
                        for j in range(i+1, len(df)):
                            future = df.iloc[j]
                            
                            if res.signal == "BUY":
                                if future['low'] <= sl:
                                    outcome = "LOSS"
                                    pnl = -sl_dist
                                    exit_idx = j
                                    break
                                if future['high'] >= tp:
                                    outcome = "WIN"
                                    pnl = tp_dist
                                    exit_idx = j
                                    break
                            else: # SELL
                                if future['high'] >= sl:
                                    outcome = "LOSS"
                                    pnl = -sl_dist
                                    exit_idx = j
                                    break
                                if future['low'] <= tp:
                                    outcome = "WIN"
                                    pnl = tp_dist
                                    exit_idx = j
                                    break
                        
                        if outcome != "OPEN":
                            if outcome == "WIN":
                                results[name]["wins"] += 1
                            else:
                                results[name]["losses"] += 1
                            
                            results[name]["trades"].append(pnl)
                            results[name]["skip_until"] = exit_idx + 1
                            
                except Exception as e:
                    # print(f"Error in {name}: {e}")
                    pass

        print("\nBacktest Complete." + " " * 20)
        self._print_summary(results)

    def _print_summary(self, results):
        print(f"\n--- FINAL SUMMARY: {self.symbol} ---")
        # Sort strategies by total PnL
        sorted_res = sorted(results.items(), key=lambda x: sum(x[1]["trades"]), reverse=True)
        
        for name, stats in sorted_res:
            total = stats["wins"] + stats["losses"]
            wr = (stats["wins"] / total * 100) if total > 0 else 0
            pnl = sum(stats["trades"])
            print(f"  {name:<25}: {total:>3} trades, {wr:>5.1f}% WR, PnL: {pnl:>8.2f}")

if __name__ == "__main__":
    load_dotenv()
    
    # Define the pairs and timeframes you want to test here
    TEST_PAIRS = [
        ("Volatility 10 Index", mt5.TIMEFRAME_H1, "1h"),
        ("Volatility 25 Index", mt5.TIMEFRAME_H1, "1h"),
        ("EURUSD", mt5.TIMEFRAME_H1, "1h")
    ]

    for sym, tf, tf_name in TEST_PAIRS:
        bt = Backtester(sym, tf, tf_name)
        bt.run()