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
from strategies.fvg_strategy import FVGStrategy

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
    "SMA Crossover": SMACrossoverStrategy(),
    "FVG": FVGStrategy()
}

# Settings
SYMBOL = "Volatility 10 Index"
TIMEFRAMES = {
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4
}

# Vol 10 Specific Risk Settings (from settings.py or defaults)
SL_ATR_MULT = 1.5
TP_ATR_MULT = 1.5

def get_data(symbol, timeframe, n=10000): # Increased to 10000 for maximum accuracy
    if not mt5.initialize():
        print(f"MT5 Init Failed: {mt5.last_error()}", flush=True)
        return None
    
    # Try different symbol names
    symbols_to_try = [symbol, "Volatility 10 Index", "R_10", "Vol 10 Index"]
    
    rates = None
    for sym in symbols_to_try:
        rates = mt5.copy_rates_from_pos(sym, timeframe, 0, n)
        if rates is not None:
            # print(f"Successfully loaded data for {sym}", flush=True)
            break
            
    if rates is None:
        print(f"Failed to get data for {symbol} (tried {symbols_to_try}): {mt5.last_error()}", flush=True)
        return None
            
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    # Calculate ATR for risk management
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    
    # Pre-calculate common indicators to speed up
    # (Strategies calculate their own, but we need ATR for SL/TP)
    
    return df

def run_backtest(symbol, tf_name, timeframe_enum):
    print(f"\n--- Testing {symbol} on {tf_name} ---", flush=True)
    
    df = get_data(symbol, timeframe_enum)
    if df is None:
        return None
        
    print(f"Data loaded: {len(df)} candles", flush=True)
    
    # Initialize Tracking
    results = {}
    for name in strategies:
        results[name] = {"wins": 0, "losses": 0, "trades": [], "skip_until": 0}
    
    # Iterate through candles
    # Start from index 300 to ensure enough history for indicators
    for i in range(300, len(df)):
        if i % 100 == 0:
            print(f"Processing candle {i}/{len(df)}...", flush=True)
            
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
                print(f"Error in {strategy_name}: {e}", flush=True)
                pass

    return results

if __name__ == "__main__":
    final_results = {}
    all_configs = [] # Store flattened results for ranking

    for name, tf_enum in TIMEFRAMES.items():
        res = run_backtest(SYMBOL, name, tf_enum)
        if res:
            final_results[name] = res
            
    print("\n" + "="*60)
    print("📊 DETAILED BREAKDOWN BY TIMEFRAME")
    print("="*60)
    
    for tf, data in final_results.items():
        print(f"\n--- {tf} Results ---")
        
        # Sort by PnL
        sorted_strategies = sorted(data.items(), key=lambda x: sum(x[1]["trades"]), reverse=True)
        
        for strat_name, res in sorted_strategies:
            total = res["wins"] + res["losses"]
            wr = (res["wins"] / total * 100) if total > 0 else 0
            pnl = sum(res["trades"])
            print(f"  {strat_name:<25}: {total:>3} trades, {wr:>5.1f}% WR, PnL: {pnl:>8.2f}")
            
            all_configs.append({
                "strategy": strat_name,
                "timeframe": tf,
                "pnl": pnl,
                "wr": wr,
                "trades": total
            })

    print("\n" + "="*60)
    print("🏆 GRAND CHAMPIONS: BEST CONFIGS FOR VOLATILITY 10 🏆")
    print("="*60)
    
    # Sort all configurations by PnL descending
    all_configs.sort(key=lambda x: x["pnl"], reverse=True)
    
    if not all_configs:
        print("No trades executed.")
    else:
        for i, config in enumerate(all_configs[:5]):
            print(f"{i+1}. {config['strategy'].upper()} ({config['timeframe']})")
            print(f"   💰 PnL: {config['pnl']:.2f} | 🎯 Win Rate: {config['wr']:.1f}% | 📉 Trades: {config['trades']}")
            print("-" * 50)
            
        best = all_configs[0]
        print("\n" + "="*60)
        print("🚀 ACTION REQUIRED: UPDATE YOUR settings.py")
        print("="*60)
        print(f"Based on this backtest, update 'Volatility 10 Index' in config/settings.py to:")
        print("")
        print(f"    'Volatility 10 Index': {{")
        print(f"        \"strategies\": [")
        print(f"            {{'strategy': '{best['strategy']}', 'timeframe': '{best['timeframe']}'}},")
        print(f"        ],")
        print(f"        \"min_confluence\": 1")
        print(f"    }},")
        print("")
            
