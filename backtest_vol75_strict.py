
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

# Initialize Strategies
strategies = {
    "macd": MACDCrossStrategy(),
    "cci": CCITrendStrategy(),
    "rsi_stoch": RSIStochStrategy(),
    "stoch": StochasticStrategy(),
    "sar": ParabolicSARStrategy(),
    "support_resistance": SupportResistanceStrategy(tolerance_pct=0.005),
    "candlestick": CandlestickPatternStrategy()
}

# Settings
SYMBOL = "Volatility 75 Index"
TIMEFRAMES = {
    "15m": mt5.TIMEFRAME_M15
}

# Vol 75 Specific Risk Settings
SL_ATR_MULT = 1.5
TP_ATR_MULT = 1.5

def get_data(symbol, timeframe, n=1000): # Faster load
    if not mt5.initialize():
        print(f"MT5 Init Failed: {mt5.last_error()}", flush=True)
        return None
    
    # Try different symbol names
    symbols_to_try = [symbol, "Volatility 75 Index", "R_75", "Vol 75 Index"]
    
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
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    return df

def run_backtest(symbol, tf_name, timeframe_enum):
    print(f"\n--- Testing {symbol} on {tf_name} ---", flush=True)
    
    # DEBUG: Track ATR and Spread stats
    total_atr = 0
    count_atr = 0
    
    df = get_data(symbol, timeframe_enum)
    if df is None:
        return None
        
    print(f"Data loaded: {len(df)} candles", flush=True)
    
    # Initialize Tracking
    variations = {
        "Current Settings (Confluence>=2)": {"wins": 0, "losses": 0, "trades": [], "skip_until": 0},
        "Any + RSI + EMA200": {"wins": 0, "losses": 0, "trades": [], "skip_until": 0},
        "Strict (Conf + S/R)": {"wins": 0, "losses": 0, "trades": [], "skip_until": 0},
    }

    # Pre-calculate RSI and EMA 200 for Global Filter
    rsi_ind = ta.momentum.RSIIndicator(close=df["close"], window=14)
    df["rsi"] = rsi_ind.rsi()
    
    ema_trend = ta.trend.EMAIndicator(close=df["close"], window=200)
    df["ema_200"] = ema_trend.ema_indicator()
    
    for i in range(300, len(df)):
        # Optimization: Sliding Window
        start_idx = max(0, i - 300)
        current_slice = df.iloc[start_idx:i+1].copy()
        current_candle = current_slice.iloc[-1]
        
        if i % 500 == 0:
            print(f"Processing candle {i}/{len(df)}...", flush=True)
            
        # DEBUG: Accumulate ATR
        if 'atr' in current_candle and not pd.isna(current_candle['atr']):
            total_atr += current_candle['atr']
            count_atr += 1
            
        # Get Global RSI and EMA
        current_rsi = current_candle['rsi']
        current_ema = current_candle['ema_200']
        current_close = current_candle['close']

        # 1. Get Strategy Signals (MACD, CCI, RSI+Stoch, Stoch, SAR)
        signals = []
        
        # MACD
        try:
            res = strategies["macd"].analyse(current_slice, symbol)
            if res.signal in ["BUY", "SELL"]:
                signals.append(res.signal)
        except:
            pass

        # CCI
        try:
            res = strategies["cci"].analyse(current_slice, symbol)
            if res.signal in ["BUY", "SELL"]:
                signals.append(res.signal)
        except:
            pass

        # RSI Stoch
        try:
            res = strategies["rsi_stoch"].analyse(current_slice, symbol)
            if res.signal in ["BUY", "SELL"]:
                signals.append(res.signal)
        except:
            pass

        # Stoch
        try:
            res = strategies["stoch"].analyse(current_slice, symbol)
            if res.signal in ["BUY", "SELL"]:
                signals.append(res.signal)
        except:
            pass

        # Parabolic SAR
        try:
            res = strategies["sar"].analyse(current_slice, symbol)
            if res.signal in ["BUY", "SELL"]:
                signals.append(res.signal)
        except:
            pass

        # 2. Confluence Check (>= 2 votes)
        buy_votes = signals.count("BUY")
        sell_votes = signals.count("SELL")
        
        confluence_signal = "NONE"
        if buy_votes >= 2:
            confluence_signal = "BUY"
        elif sell_votes >= 2:
            confluence_signal = "SELL"
            
        # DEBUG: Log votes
        if i % 200 == 0:
            print(f"Candle {i}: Buys={buy_votes}, Sells={sell_votes}")

        # 2. Get Filter Signals
        sr_signal = "NONE"
        try:
            sr_res = strategies["support_resistance"].analyse(current_slice, symbol)
            if sr_res.signal in ["BUY", "SELL"]:
                sr_signal = sr_res.signal
        except:
            pass
            
        candle_signal = "NONE"
        try:
            candle_res = strategies["candlestick"].analyse(current_slice, symbol)
            if candle_res.signal in ["BUY", "SELL"]:
                candle_signal = candle_res.signal
        except:
            pass
        
        # Evaluate Variations
        for var_name in variations:
            if i < variations[var_name]["skip_until"]:
                continue
                
            execute = False
            direction = "NONE"
            
            # Baseline: Confluence >= 2
            if var_name == "Current Settings (Confluence>=2)":
                if confluence_signal != "NONE":
                    execute = True
                    direction = confluence_signal
                
            # Any + RSI + EMA200
            elif var_name == "Any + RSI + EMA200":
                # Check for ANY signal
                has_buy = buy_votes >= 1
                has_sell = sell_votes >= 1
                
                # Apply RSI + EMA 200 Safety
                if has_buy and current_rsi < 70 and current_close > current_ema:
                    execute = True
                    direction = "BUY"
                elif has_sell and current_rsi > 30 and current_close < current_ema:
                    execute = True
                    direction = "SELL"
                
                # Conflict resolution
                if has_buy and has_sell:
                     execute = False
                     direction = "NONE"

            # Strict: Confluence + S/R
            elif var_name == "Strict (Conf + S/R)":
                if confluence_signal != "NONE" and confluence_signal == sr_signal:
                    execute = True
                    direction = confluence_signal
            
            if execute and direction != "NONE":
                entry_price = current_candle['close']
                atr = current_candle['atr']
                
                sl_dist = atr * SL_ATR_MULT
                tp_dist = atr * TP_ATR_MULT
                
                if direction == "BUY":
                    sl = entry_price - sl_dist
                    tp = entry_price + tp_dist
                else:
                    sl = entry_price + sl_dist
                    tp = entry_price - tp_dist
                    
                # Simulate Outcome
                outcome = "OPEN"
                pnl = 0.0
                exit_index = i
                
                for j in range(i+1, len(df)):
                    future_candle = df.iloc[j]
                    high = future_candle['high']
                    low = future_candle['low']
                    
                    if direction == "BUY":
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
                    variations[var_name]["wins"] += 1
                    variations[var_name]["trades"].append(pnl)
                    variations[var_name]["skip_until"] = exit_index + 1
                elif outcome == "LOSS":
                    variations[var_name]["losses"] += 1
                    variations[var_name]["trades"].append(pnl)
                    variations[var_name]["skip_until"] = exit_index + 1

    # Report
    if count_atr > 0:
        print(f"Avg ATR ({tf_name}): {total_atr / count_atr:.5f}")

    print(f"Results for {tf_name}:")
    for var_name, data in variations.items():
        total = data["wins"] + data["losses"]
        wr = (data["wins"] / total * 100) if total > 0 else 0
        pnl = sum(data["trades"])
        print(f"  {var_name}: {total} trades, {wr:.1f}% WR, PnL: {pnl:.2f}")
    
    return {tf_name: variations}

if __name__ == "__main__":
    from loguru import logger
    logger.remove()
    
    final_results = {}
    for name, tf_enum in TIMEFRAMES.items():
        res = run_backtest(SYMBOL, name, tf_enum)
        if res:
            final_results[name] = res[name]
            
    print("\n--- FINAL SUMMARY ---")
    for tf, data in final_results.items():
        print(f"\n{tf}:")
        for var_name, res in data.items():
            total = res["wins"] + res["losses"]
            wr = (res["wins"] / total * 100) if total > 0 else 0
            pnl = sum(res["trades"])
            print(f"  {var_name}: {total} trades, {wr:.1f}% WR, PnL: {pnl:.2f}")
