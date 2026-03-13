import MetaTrader5 as mt5
from dotenv import load_dotenv
import os

load_dotenv()

# Initialize MT5
path = os.getenv("MT5_PATH")
if not mt5.initialize(path=path):
    print("initialize() failed")
    mt5.shutdown()
    exit()

# List of symbols to check
symbols = [
    "Volatility 10 Index",
    "Volatility 25 Index",
    "Volatility 50 Index",
    "Volatility 75 Index",
    "Volatility 100 Index",
    "EURUSD",
    "XAUUSD"
]

print(f"{'Symbol':<25} | {'Min Lot':<10} | {'Max Lot':<10} | {'Vol Step':<10} | {'Contract Size':<15}")
print("-" * 80)

for sym in symbols:
    info = mt5.symbol_info(sym)
    if info:
        print(f"{sym:<25} | {info.volume_min:<10} | {info.volume_max:<10} | {info.volume_step:<10} | {info.trade_contract_size:<15}")
    else:
        print(f"{sym:<25} | Not Found")

mt5.shutdown()
