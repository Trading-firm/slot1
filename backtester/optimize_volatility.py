import sys
import os
import pandas as pd
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester.backtest import run_backtest
from broker.connector import ForexBroker
from utils.logger import logger

def optimize():
    pairs = [
        "Volatility 10 Index",
        "Volatility 25 Index",
        "Volatility 50 Index",
        "Volatility 75 Index",
        "Volatility 100 Index",
        "EURUSD"
    ]
    
    timeframes = ["15m", "1h"] 
    
    strategies = [
        "ema_rsi",
        "bollinger_breakout",
        "mean_reversion",
        "macd_cross",
        "stochastic",
        "atr_breakout",
        "sma_crossover",
        "cci_trend",
        "parabolic_sar",
        "rsi_stoch"
    ]
    
    results = []
    
    print("Starting optimization... This may take a while.")
    
    for pair in pairs:
        print(f"\nProcessing {pair}...")
        for tf in timeframes:
            # Fetch data once per pair/tf
            try:
                broker = ForexBroker()
                df = broker.fetch_ohlcv(pair=pair, timeframe=tf, limit=5000)
                if df.empty or len(df) < 100:
                    print(f"  Skipping {pair} {tf}: Not enough data")
                    continue
            except Exception as e:
                print(f"  Error fetching {pair} {tf}: {e}")
                continue
                
            best_strat = None
            best_profit = -1000.0
            
            for strat in strategies:
                try:
                    profit_pct, win_rate, total_trades, drawdown = run_backtest(
                        pair=pair,
                        timeframe=tf,
                        strategy_name=strat,
                        verbose=False,
                        df=df
                    )
                    
                    results.append({
                        "pair": pair,
                        "timeframe": tf,
                        "strategy": strat,
                        "profit_pct": profit_pct,
                        "win_rate": win_rate,
                        "trades": total_trades,
                        "drawdown": drawdown
                    })
                    
                    if profit_pct > best_profit:
                        best_profit = profit_pct
                        best_strat = strat
                    
                    print(f"  {tf:3} | {strat:20} | Profit: {profit_pct:6.2f}% | WR: {win_rate:5.1f}% | Trades: {total_trades:3} | DD: {drawdown:6.2f}%")
                    
                except Exception as e:
                    print(f"  Error testing {strat}: {e}")
            
            print(f"  >> Best for {pair} {tf}: {best_strat} ({best_profit:.2f}%)")

    # Summary
    print("\n\n====================================================================================================")
    print("OPTIMIZATION SUMMARY (Multi-Timeframe)")
    print("====================================================================================================")
    print(f"{'Pair':20} | {'TF':3} | {'Strategy':20} | {'Profit %':8} | {'Win Rate':8} | {'Trades':6} | {'DD %':6}")
    print("-" * 100)
    
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        # Filter profitable results
        profitable = df_results[df_results["profit_pct"] > 0]
        
        final_config = {}
        
        for pair in pairs:
            pair_config = []
            
            # Use all results, not just profitable ones, to find best per timeframe
            pair_results = df_results[df_results["pair"] == pair]
            
            if pair_results.empty:
                continue
                
            # Iterate through timeframes to find best strategy per timeframe
            for tf in timeframes:
                tf_results = pair_results[pair_results["timeframe"] == tf]
                if not tf_results.empty:
                    # Get top 2 best strategies for this timeframe, sorted by Profit %
                    top_strategies = tf_results.sort_values(by="profit_pct", ascending=False).head(2)
                    
                    for idx, row in top_strategies.iterrows():
                        if row["profit_pct"] > 0:
                            print(f"{pair:20} | {tf:3} | {row['strategy']:20} | {row['profit_pct']:6.2f}% | {row['win_rate']:6.1f}% | {row['trades']:6} | {row['drawdown']:6.2f}%")
                            pair_config.append({
                                "strategy": row["strategy"],
                                "timeframe": tf
                            })
            
            if pair_config:
                final_config[pair] = pair_config

        print("\n\nSUGGESTED CONFIGURATION (Copy to settings.py):")
        print("STRATEGY_CONFIG = {")
        for pair, configs in final_config.items():
            print(f"    '{pair}': [")
            for cfg in configs:
                print(f"        {{'strategy': '{cfg['strategy']}', 'timeframe': '{cfg['timeframe']}'}},")
            print(f"    ],")
        print("}")

    else:
        print("No results found.")

if __name__ == "__main__":
    optimize()
