"""
scripts/test_entry_engine.py
─────────────────────────────
Phase 4 validation: pull real gold data, run the entire pipeline
(Phase 1 + 2 + 3 + 4), print what the entry engine decides.

Also shows a rolling historical test so you can eyeball how often setups fire
and what they look like.
"""
import os, sys, sqlite3
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.mtf_analysis import analyze_mtf, BIAS_NEUTRAL
from strategies.level_memory import LevelMemory, DB_PATH_DEFAULT
from strategies.entry_engine import find_entry

SYMBOL = "XAUUSD"


def reset_db():
    if os.path.exists(DB_PATH_DEFAULT):
        with sqlite3.connect(DB_PATH_DEFAULT) as c:
            c.execute("DELETE FROM levels WHERE symbol=?", (SYMBOL,))


def run_current():
    df_h4  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H4,  count=400)
    df_h1  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H1,  count=500)
    df_m15 = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=500)

    mem = LevelMemory()
    mem.update(SYMBOL, "H4",  df_h4)
    mem.update(SYMBOL, "H1",  df_h1)
    mem.update(SYMBOL, "M15", df_m15)

    mtf = analyze_mtf(df_h4, df_h1, df_m15)
    setup = find_entry(mtf, mem, df_m15, SYMBOL)

    print("="*90)
    print(f"PHASE 4 — current state on {SYMBOL}")
    print("="*90)
    print(f"  BIAS: {mtf.bias} | {mtf.reason}")
    print(f"\n  H4  {mtf.h4_struct.trend}")
    print(f"  H1  {mtf.h1_struct.trend}")
    print(f"  M15 {mtf.m15_struct.trend}")
    print()
    if setup is None:
        print("  NO ENTRY — bias or structure doesn't support a trade right now.")
        return
    print(f"  ▶ ENTRY SETUP: {setup.direction} @ ${setup.entry_price:.2f}")
    print(f"    Scenario:     {setup.scenario}")
    print(f"    Reason:       {setup.reason}")
    print(f"    SL:           ${setup.sl:.2f}  (invalidates at ${setup.invalidation_price:.2f})")
    print(f"    TP_A (main):  ${setup.tp_a:.2f}")
    print(f"    TP_B (scalp): entry {'+' if setup.direction=='BUY' else '-'} ${setup.tp_b_profit_usd} when P/L reaches target")
    dist_sl = abs(setup.entry_price - setup.sl)
    dist_tp = abs(setup.tp_a - setup.entry_price)
    rr = dist_tp / dist_sl if dist_sl > 0 else 0
    print(f"    R:R (main):   1:{rr:.2f}  (risk ${dist_sl:.2f} / reward ${dist_tp:.2f})")


def run_history(step: int = 10, window: int = 50):
    """Replay the pipeline step-by-step over recent history."""
    df_h4  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H4,  count=1200)
    df_h1  = fetch_candles(SYMBOL, mt5.TIMEFRAME_H1,  count=3000)
    df_m15 = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=10000)

    mem = LevelMemory()
    # Seed memory — incremental rebuild would be proper but for validation
    # we just use the full-length memory state per step.

    print("\n" + "="*90)
    print(f"PHASE 4 — rolling replay last {window} M15 steps (every {step} bars)")
    print("="*90)
    hits = []
    end_idxs = range(len(df_m15) - window, len(df_m15), step)
    for i in end_idxs:
        m15_slice = df_m15.iloc[:i+1]
        end_time = m15_slice["time"].iloc[-1]
        h4_slice = df_h4[df_h4["time"] <= end_time]
        h1_slice = df_h1[df_h1["time"] <= end_time]
        if len(h4_slice) < 100 or len(h1_slice) < 100: continue

        # Rebuild memory from scratch for this snapshot (slow but correct)
        reset_db()
        mem.update(SYMBOL, "H4",  h4_slice)
        mem.update(SYMBOL, "H1",  h1_slice)
        mem.update(SYMBOL, "M15", m15_slice)
        mtf = analyze_mtf(h4_slice, h1_slice, m15_slice)
        setup = find_entry(mtf, mem, m15_slice, SYMBOL)
        if setup:
            hits.append((end_time, mtf.bias, setup))
            print(f"  {str(end_time):<22} bias={mtf.bias:<8} {setup.direction:<4} @ ${setup.entry_price:.2f}  SL ${setup.sl:.2f}  TP ${setup.tp_a:.2f}  ({setup.scenario})")

    print(f"\n  Total setups in replay: {len(hits)}")


def main():
    if not connect(): return
    mt5.symbol_select(SYMBOL, True)
    reset_db()
    run_current()
    # 2000 M15 bars ≈ 20 days, step 30 = every 7.5h → ~65 snapshots
    run_history(step=30, window=2000)
    disconnect()


if __name__ == "__main__":
    main()
