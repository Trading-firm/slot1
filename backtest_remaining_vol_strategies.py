import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta
from datetime import datetime
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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

# Initialize Strategies
strategies = {
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
    "SMA Crossover": SMACrossoverStrategy()
}

# Settings
SYMBOLS = ["Volatility 50 Index", "Volatility 75 Index", "Volatility 100 Index"]
TIMEFRAME_NAME = "1h"
TIMEFRAME_ENUM = mt5.TIMEFRAME_H1

# Risk Settings (Standard 1:1)
SL_ATR_MULT = 1.5
TP_ATR_MULT = 1.5

def get_data(symbol, timeframe, n=1000): 
    if not mt5.initialize():
        print(f"MT5 Init Failed: {mt5.last_error()}", flush=True)
        return None
    
    # Try different symbol names
    symbols_to_try = [symbol, symbol.replace("Volatility", "Vol"), symbol.replace("Volatility ", "R_")]
    
    rates = None
    for sym in symbols_to_try:
        rates = mt5.copy_rates_from_pos(sym, timeframe, 0, n)
        if rates is not None and len(rates) > 0:
            # print(f"Successfully loaded data for {sym}", flush=True)
            break
            
    if rates is None or len(rates) == 0:
        print(f"Failed to get data for {symbol} (tried {symbols_to_try}): {mt5.last_error()}", flush=True)
        return None
            
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    # Calculate ATR for risk management
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    
    return df

def run_backtest(symbol, tf_name, timeframe_enum):
    print(f"\n{'='*60}")
    print(f"Testing {symbol} on {tf_name}")
    print(f"{'='*60}", flush=True)
    
    df = get_data(symbol, timeframe_enum)
    if df is None:
        return None
        
    print(f"Data loaded: {len(df)} candles", flush=True)
    
    start_date = df.iloc[300]['time']
    end_date = df.iloc[-1]['time']
    duration = end_date - start_date
    print(f"Backtest Period: {start_date} to {end_date} ({duration})", flush=True)
    
    # Initialize Tracking
    results = {}
    for name in strategies:
        results[name] = {"wins": 0, "losses": 0, "trades": [], "skip_until": 0}
    
    # Iterate through candles
    # Start from index 300 to ensure enough history for indicators
    for i in range(300, len(df)):
        # if i % 200 == 0:
        #     print(f"Processing candle {i}/{len(df)}...", flush=True)
            
        current_candle = df.iloc[i]
        
        # Optimization: Sliding Window
        start_idx = max(0, i - 300)
        current_slice = df.iloc[start_idx:i+1].copy()
        
        for strategy_name, strategy in strategies.items():
            # Check if we are currently in a trade for this strategy
            if i < results[strategy_name]["skip_until"]:
                continue
                
            try:
                res = strategy.analyse(current_slice, symbol)
                signal = res.signal
                
                if signal in ["BUY", "SELL"]:
                    # Execute Trade
                    entry_price = res.close # Use close price from signal result
                    sl = res.stop_loss
                    tp = res.take_profit

                    # Ensure the strategy returned a valid SL/TP
                    if sl == 0.0 or tp == 0.0:
                        continue
                        
                    # Simulate Outcome
                    outcome = "OPEN"
                    pnl = 0.0
                    exit_index = i
                    
                    # PNL is the distance from entry to TP.
                    # SL distance is also calculated for loss case.
                    # This assumes a fixed SL/TP and doesn't account for slippage.
                    tp_dist = abs(tp - entry_price)
                    sl_dist = abs(sl - entry_price)

                    for j in range(i+1, len(df)):
                        future_candle = df.iloc[j]
                        high = future_candle['high']
                        low = future_candle['low']
                        
                        if signal == "BUY":
                            if low <= sl:
                                outcome = "LOSS"
                                pnl = -sl_dist
                                exit_index = j
                                break
                            if high >= tp:
                                outcome = "WIN"
                                pnl = tp_dist
                                exit_index = j
                                break
                        else:
                            if high >= sl:
                                outcome = "LOSS"
                                pnl = -sl_dist
                                exit_index = j
                                break
                            if low <= tp:
                                outcome = "WIN"
                                pnl = tp_dist
                                exit_index = j
                                break
                    
                    if outcome == "WIN":
                        results[strategy_name]["wins"] += 1
                        results[strategy_name]["trades"].append(pnl)
                        results[strategy_name]["skip_until"] = exit_index + 1
                    elif outcome == "LOSS":
                        results[strategy_name]["losses"] += 1
                        results[strategy_name]["trades"].append(pnl)
                        results[strategy_name]["skip_until"] = exit_index + 1
                        
            except Exception as e:
                # print(f"Error in {strategy_name}: {e}", flush=True)
                pass

    return results

if __name__ == "__main__":
    for symbol in SYMBOLS:
        res = run_backtest(symbol, TIMEFRAME_NAME, TIMEFRAME_ENUM)
        
        if res:
            print(f"\n--- FINAL SUMMARY: {symbol} (Sorted by PnL) ---")
            
            # Sort by PnL
            sorted_strategies = sorted(res.items(), key=lambda x: sum(x[1]["trades"]), reverse=True)
            
            for strat_name, stats in sorted_strategies:
                total = stats["wins"] + stats["losses"]
                wr = (stats["wins"] / total * 100) if total > 0 else 0
                pnl = sum(stats["trades"])
                print(f"  {strat_name:<25}: {total:>3} trades, {wr:>5.1f}% WR, PnL: {pnl:>8.2f}")
        else:
            print(f"No results for {symbol}")
