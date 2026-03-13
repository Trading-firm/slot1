import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta
import os
from datetime import datetime
from dotenv import load_dotenv

# Import Strategies
from strategies.ema_rsi import EMARSIStrategy
from strategies.bollinger_breakout import BollingerBreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.macd_cross import MACDCrossStrategy
from strategies.stochastic_oscillator import StochasticStrategy
from strategies.atr_breakout import ATRBreakoutStrategy
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.cci_trend import CCITrendStrategy
from strategies.parabolic_sar import ParabolicSARStrategy
from strategies.rsi_stoch import RSIStochStrategy
from strategies.support_resistance import SupportResistanceStrategy
from strategies.candlestick_pattern import CandlestickPatternStrategy

# Load environment variables
load_dotenv()

# Initialize MT5
if not mt5.initialize():
    print("MT5 Init Failed")
    quit()

# Configuration per Symbol
CONFIG = {
    "Volatility 10 Index": {
        "timeframe": mt5.TIMEFRAME_H1,
        "tf_name": "1h",
        "sl_atr": 1.5,
        "tp_atr": 1.5,
        "strategies": {
            #"ema_rsi": EMARSIStrategy(),
            #"bollinger": BollingerBreakoutStrategy(),
            #"mean_reversion": MeanReversionStrategy(),
            "macd": MACDCrossStrategy(),
            "stochastic": StochasticStrategy(),
            #"atr_breakout": ATRBreakoutStrategy(),
            #"sma_cross": SMACrossoverStrategy(),
            "cci": CCITrendStrategy(),
            #"sar": ParabolicSARStrategy(),
            "rsi_stoch": RSIStochStrategy(),
        }
    },
    "Volatility 25 Index": {
        "timeframe": mt5.TIMEFRAME_H1,
        "tf_name": "1h",
        "sl_atr": 1.2,
        "tp_atr": 1.5,
        "strategies": {
            "bollinger": BollingerBreakoutStrategy(),
            "macd": MACDCrossStrategy(),
            "cci": CCITrendStrategy(),
        }
    },
    "Volatility 75 Index": {
        "timeframe": mt5.TIMEFRAME_M15,
        "tf_name": "15m",
        "sl_atr": 1.5,
        "tp_atr": 1.5,
        "strategies": {
            "stochastic": StochasticStrategy(),
            "macd": MACDCrossStrategy(),
            "cci": CCITrendStrategy(),
            "sar": ParabolicSARStrategy(),
            "rsi_stoch": RSIStochStrategy(),
        }
    }
}

# Common Confirmation Strategies
SR_STRATEGY = SupportResistanceStrategy(tolerance_pct=0.005)
CANDLE_STRATEGY = CandlestickPatternStrategy()

def get_data(symbol, timeframe, n=5000):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None:
        # Try alternatives
        alts = [symbol, symbol.replace("Volatility", "R").replace(" Index", ""), "Vol " + symbol.split(" ")[1] + " Index"]
        for alt in alts:
            rates = mt5.copy_rates_from_pos(alt, timeframe, 0, n)
            if rates is not None:
                break
        
    if rates is None:
        print(f"Failed to get data for {symbol}")
        return None
            
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Calculate global ATR for SL/TP
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    
    return df

def run_dream_backtest(symbol_name, n_candles=500):
    cfg = CONFIG.get(symbol_name)
    if not cfg:
        print(f"No config for {symbol_name}")
        return

    print(f"\n--- Testing {symbol_name} ({cfg['tf_name']}) ---")
    print("Algorithm: Confluence >= 2 AND S/R Bounce AND Candlestick Pattern")
    
    df = get_data(symbol_name, cfg['timeframe'], n=n_candles)
    if df is None:
        return

    print(f"Data loaded: {len(df)} candles")
    
    # Tracking
    variations = {
        "Baseline (Confluence>=2)": {"wins": 0, "losses": 0, "pnl": []},
        "Strict (Conf+SR)": {"wins": 0, "losses": 0, "pnl": []},
        "Dream (Conf+SR+Candle)": {"wins": 0, "losses": 0, "pnl": []}
    }
    
    # Skip until index for each variation to avoid overlapping trades
    skip_until = {
        "Baseline (Confluence>=2)": 0,
        "Strict (Conf+SR)": 0,
        "Dream (Conf+SR+Candle)": 0
    }
    
    strategies = cfg['strategies']
    
    # Process
    start_time = datetime.now()
    # We need at least 200 candles for EMA 200
    window_size = 205
    start_loop = window_size
    
    for i in range(start_loop, len(df)):
        if i % 100 == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"Processing candle {i}/{len(df)}... ({elapsed:.1f}s)", flush=True)

        start_idx = max(0, i - window_size)
        current_slice = df.iloc[start_idx:i+1].copy()
        current_candle = current_slice.iloc[-1]
        
        # 1. Check Confluence (Vote >= 2)
        votes = {"BUY": 0, "SELL": 0}
        
        for name, strat in strategies.items():
            try:
                res = strat.analyse(current_slice, symbol_name)
                if res.signal in ["BUY", "SELL"]:
                    votes[res.signal] += 1
            except:
                pass
                
        base_signal = "NONE"
        if votes["BUY"] >= 2:
            base_signal = "BUY"
        elif votes["SELL"] >= 2:
            base_signal = "SELL"
            
        if base_signal == "NONE":
            continue
            
        # 2. Check Support/Resistance
        sr_res = SR_STRATEGY.analyse(current_slice, symbol_name)
        sr_match = (sr_res.signal == base_signal)
            
        # 3. Check Candlestick Pattern
        candle_res = CANDLE_STRATEGY.analyse(current_slice, symbol_name)
        candle_match = (candle_res.signal == base_signal)
        
        # Determine which variations trigger
        triggers = {
            "Baseline (Confluence>=2)": True,
            "Strict (Conf+SR)": sr_match,
            "Dream (Conf+SR+Candle)": sr_match and candle_match
        }
        
        # Execute Trades for each variation
        entry_price = current_candle['close']
        atr = current_candle['atr']
        sl_dist = atr * cfg['sl_atr']
        tp_dist = atr * cfg['tp_atr']
        
        for var_name, triggered in triggers.items():
            if not triggered:
                continue
                
            if i < skip_until[var_name]:
                continue
                
            # Execute Trade Logic
            signal = base_signal
            if signal == "BUY":
                sl = entry_price - sl_dist
                tp = entry_price + tp_dist
            else:
                sl = entry_price + sl_dist
                tp = entry_price - tp_dist
                
            # Simulate
            outcome = "OPEN"
            pnl = 0.0
            exit_idx = i
            
            for j in range(i+1, len(df)):
                future = df.iloc[j]
                high = future['high']
                low = future['low']
                
                if signal == "BUY":
                    if low <= sl:
                        outcome = "LOSS"
                        pnl = -sl_dist
                        exit_idx = j
                        break
                    if high >= tp:
                        outcome = "WIN"
                        pnl = tp_dist
                        exit_idx = j
                        break
                else:
                    if high >= sl:
                        outcome = "LOSS"
                        pnl = -sl_dist
                        exit_idx = j
                        break
                    if low <= tp:
                        outcome = "WIN"
                        pnl = tp_dist
                        exit_idx = j
                        break
                        
            if outcome == "WIN":
                variations[var_name]["wins"] += 1
                variations[var_name]["pnl"].append(pnl)
                skip_until[var_name] = exit_idx + 1
            elif outcome == "LOSS":
                variations[var_name]["losses"] += 1
                variations[var_name]["pnl"].append(pnl)
                skip_until[var_name] = exit_idx + 1
            
    # Report
    print(f"Results for {symbol_name}:")
    for var_name, data in variations.items():
        total = data["wins"] + data["losses"]
        wr = (data["wins"] / total * 100) if total > 0 else 0
        total_pnl = sum(data["pnl"])
        print(f"  {var_name}: {total} trades, {wr:.1f}% WR, PnL: {total_pnl:.2f}")

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        symbol_arg = sys.argv[1]
        # Map short names
        if "10" in symbol_arg:
            run_dream_backtest("Volatility 10 Index", n_candles=1000)
        elif "25" in symbol_arg:
            run_dream_backtest("Volatility 25 Index", n_candles=1000)
        elif "75" in symbol_arg:
            run_dream_backtest("Volatility 75 Index", n_candles=1000)
    else:
        run_dream_backtest("Volatility 10 Index", n_candles=500)
        run_dream_backtest("Volatility 25 Index", n_candles=500)
        run_dream_backtest("Volatility 75 Index", n_candles=500)
