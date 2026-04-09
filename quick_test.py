"""
quick_test.py
──────────────
Quick test to verify BTCUSD strategy signal generation.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker.mt5_connector import connect, disconnect, fetch_candles
from config.markets import MARKETS
from strategies.signal_engine import generate_signal

print("Testing BTCUSD Strategy...\n")

if not connect():
    print("Failed to connect to MT5")
    sys.exit(1)

try:
    cfg = MARKETS["BTCUSD"]
    print(f"Config: {cfg}\n")

    df = fetch_candles("BTCUSD", cfg["timeframe"], count=300)
    print(f"Downloaded {len(df)} candles")

    if df.empty:
        print("No data!")
    else:
        print(f"Latest candle: {df['Close'].iloc[-1]:.2f}")
        print(f"Data range: {df['time'].iloc[0]} to {df['time'].iloc[-1]}\n")

        signal = generate_signal(df, cfg)
        print(f"Signal:    {signal.direction}")
        print(f"Reason:    {signal.reason}")
        print(f"Base:      {signal.base_signal}")
        print(f"RSI:       {signal.rsi}")
        print(f"ATR:       {signal.atr:.2f}")
        print(f"EMA200:    {signal.ema_trend:.2f}")
        if signal.direction != "NONE":
            print(f"SL:        {signal.sl:.2f}")
            print(f"TP1:       {signal.tp1:.2f}")
            print(f"TP2:       {signal.tp2:.2f}")
            print(f"TP3:       {signal.tp3:.2f}")

finally:
    disconnect()
    print("\nTest complete!")
