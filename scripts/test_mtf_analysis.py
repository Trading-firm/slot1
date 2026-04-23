"""
scripts/test_mtf_analysis.py
─────────────────────────────
Phase 2 validation: pull real gold data on H4/H1/M15, run analyze_mtf,
print the bias decision + reasoning.

Also shows a rolling 10-step history so you can see bias flip over time.
"""
import os, sys
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.mtf_analysis import analyze_mtf, BIAS_BUY, BIAS_SELL

SYMBOL = "XAUUSD"


def print_current():
    df_h4  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H4,  count=400)
    df_h1  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H1,  count=500)
    df_m15 = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=500)
    r = analyze_mtf(df_h4, df_h1, df_m15)

    print("="*90)
    print(f"MTF CURRENT STATE — {SYMBOL}")
    print("="*90)
    print(f"  BIAS:    {r.bias}")
    print(f"  Reason:  {r.reason}")
    print(f"\n  H4  trend:  {r.h4_struct.trend:<10} ({r.h4_struct.reason})")
    print(f"  H1  trend:  {r.h1_struct.trend:<10} ({r.h1_struct.reason})")
    print(f"  M15 trend:  {r.m15_struct.trend:<10} ({r.m15_struct.reason})")


def rolling_history(step_h4: int = 5):
    """
    Replay analyze_mtf every `step_h4` H4-bars and show how the bias evolves.
    For each H4 snapshot, we truncate H1/M15 to the same end time.
    """
    df_h4  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H4,  count=400)
    df_h1  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H1,  count=1500)
    df_m15 = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=4000)

    print("\n" + "="*90)
    print(f"MTF ROLLING HISTORY — last 50 H4 bars, every {step_h4} bars")
    print("="*90)
    print(f"  {'H4 time':<22} {'Close':<10} {'Bias':<8} {'H4':<10} {'H1':<10} {'M15':<10}")

    for i in range(len(df_h4) - 50, len(df_h4), step_h4):
        h4_slice  = df_h4.iloc[:i+1]
        end_time  = h4_slice["time"].iloc[-1]
        h1_slice  = df_h1[df_h1["time"]  <= end_time]
        m15_slice = df_m15[df_m15["time"] <= end_time]
        if len(h1_slice) < 50 or len(m15_slice) < 50:
            continue
        r = analyze_mtf(h4_slice, h1_slice, m15_slice)
        close = h4_slice["Close"].iloc[-1]
        print(f"  {str(end_time):<22} ${close:<8.2f} {r.bias:<8} {r.h4_struct.trend:<10} {r.h1_struct.trend:<10} {r.m15_struct.trend:<10}")


def main():
    if not connect(): print("MT5 connect failed"); return
    mt5.symbol_select(SYMBOL, True)
    print_current()
    rolling_history(step_h4=5)
    disconnect()


if __name__ == "__main__":
    main()