
import sys
import os
import pandas as pd
from tabulate import tabulate

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester.backtest import run_backtest
from utils.logger import logger

def optimize_volatility():
    """
    Run batch backtests for Volatility Indices across multiple strategies.
    """
    pairs = ["Vol 10", "Vol 25", "Vol 50", "Vol 75", "Vol 100"]
    strategies = ["bollinger_breakout", "mean_reversion", "ema_rsi"]
    timeframes = ["15m", "1h"] # Testing both common timeframes

    results = []

    print("\nSTARTING VOLATILITY INDICES OPTIMIZATION\n")

    for pair in pairs:
        for strat in strategies:
            for tf in timeframes:
                print(f"Testing {pair} | {strat} | {tf} ...")
                
                try:
                    # Run backtest
                    # We capture stdout to prevent cluttering the summary output, 
                    # but we might want to see the progress. 
                    # For now, let it print.
                    profit_pct = run_backtest(
                        pair=pair, 
                        timeframe=tf, 
                        starting_cash=10000.0, 
                        strategy_name=strat
                    )
                    
                    results.append({
                        "Pair": pair,
                        "Strategy": strat,
                        "Timeframe": tf,
                        "Profit %": profit_pct
                    })
                    
                except Exception as e:
                    logger.error(f"Error testing {pair} {strat} {tf}: {e}")
                    results.append({
                        "Pair": pair,
                        "Strategy": strat,
                        "Timeframe": tf,
                        "Profit %": "ERROR"
                    })

    # Sort results by Profit % (descending)
    # Filter out errors for sorting
    valid_results = [r for r in results if isinstance(r["Profit %"], (int, float))]
    error_results = [r for r in results if not isinstance(r["Profit %"], (int, float))]
    
    valid_results.sort(key=lambda x: x["Profit %"], reverse=True)
    
    final_results = valid_results + error_results

    print("\n\nOPTIMIZATION SUMMARY")
    print("==========================")
    table_str = tabulate(final_results, headers="keys", tablefmt="grid", floatfmt=".2f")
    print(table_str)
    
    # Write to file
    with open("optimization_results.txt", "w", encoding="utf-8") as f:
        f.write("OPTIMIZATION SUMMARY\n")
        f.write("==========================\n")
        f.write(table_str)
        
        # Recommendation
        if valid_results:
            best = valid_results[0]
            msg = f"\nBEST PERFORMER: {best['Pair']} with {best['Strategy']} ({best['Timeframe']}) -> {best['Profit %']:.2f}% Profit"
            print(msg)
            f.write(msg + "\n")

            # Best per Pair
            f.write("\nBEST STRATEGY PER PAIR:\n")
            print("\nBEST STRATEGY PER PAIR:")
            pairs_seen = set()
            for r in valid_results:
                if r['Pair'] not in pairs_seen:
                    msg = f"  - {r['Pair']}: {r['Strategy']} ({r['Timeframe']}) -> {r['Profit %']:.2f}%"
                    print(msg)
                    f.write(msg + "\n")
                    pairs_seen.add(r['Pair'])

if __name__ == "__main__":
    optimize_volatility()
