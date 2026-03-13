
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from strategies.ema_rsi import EMARSIStrategy
from strategies.bollinger_rsi import BollingerRSIStrategy
from scheduler.engine import TradingEngine

def create_dummy_data(length=300):
    dates = pd.date_range(start="2023-01-01", periods=length, freq="h")
    df = pd.DataFrame({
        "open": np.random.uniform(100, 200, length),
        "high": np.random.uniform(100, 200, length),
        "low": np.random.uniform(100, 200, length),
        "close": np.random.uniform(100, 200, length),
        "volume": np.random.uniform(1000, 5000, length)
    }, index=dates)
    
    # Make sure high is highest and low is lowest
    df["high"] = df[["open", "close", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "low"]].min(axis=1)
    return df

def test_strategies():
    print("Testing Strategy Instantiation...")
    ema_strat = EMARSIStrategy()
    bb_strat = BollingerRSIStrategy()
    print("✅ Strategies instantiated.")

    print("\nTesting Indicator Calculation with Dummy Data...")
    df = create_dummy_data()
    
    # Test EMA Strategy
    try:
        res_ema = ema_strat.analyse(df.copy(), "TEST/USD")
        print(f"✅ EMA Strategy Analysis: {res_ema.signal} (Reason: {res_ema.reason})")
    except Exception as e:
        print(f"❌ EMA Strategy Failed: {e}")

    # Test Bollinger Strategy
    try:
        res_bb = bb_strat.analyse(df.copy(), "TEST/USD")
        print(f"✅ BB Strategy Analysis: {res_bb.signal} (Reason: {res_bb.reason})")
    except Exception as e:
        print(f"❌ BB Strategy Failed: {e}")
        import traceback
        traceback.print_exc()

    print("\nTesting Trading Engine Instantiation...")
    try:
        engine = TradingEngine()
        print(f"✅ Engine instantiated with strategies: {[s.__class__.__name__ for s in engine.strategies]}")
    except Exception as e:
        print(f"❌ Engine Instantiation Failed: {e}")

if __name__ == "__main__":
    test_strategies()
