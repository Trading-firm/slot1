"""
scripts/test_level_memory.py
─────────────────────────────
Phase 3 validation.

1. Clear the levels DB for XAUUSD.
2. Fetch H4/H1/M15 gold data.
3. Call LevelMemory.update() on each.
4. Print active levels per timeframe.
5. Print recently broken levels.
6. Print nearest level above/below current price.
"""
import os, sys, sqlite3
import MetaTrader5 as mt5

sys.path.append(os.getcwd())
from broker.mt5_connector import connect, disconnect, fetch_candles
from strategies.level_memory import LevelMemory, DB_PATH_DEFAULT

SYMBOL = "XAUUSD"


def clear_db():
    if os.path.exists(DB_PATH_DEFAULT):
        with sqlite3.connect(DB_PATH_DEFAULT) as c:
            c.execute("DELETE FROM levels WHERE symbol=?", (SYMBOL,))
        print(f"Cleared existing {SYMBOL} levels from {DB_PATH_DEFAULT}")


def main():
    if not connect(): return
    mt5.symbol_select(SYMBOL, True)

    clear_db()
    mem = LevelMemory()

    print("="*90)
    print(f"PHASE 3 VALIDATION: level memory on {SYMBOL}")
    print("="*90)

    # Feed each timeframe
    for tf_code, tf_name, count in [
        (mt5.TIMEFRAME_H4,  "H4",  400),
        (mt5.TIMEFRAME_H1,  "H1",  500),
        (mt5.TIMEFRAME_M15, "M15", 500),
    ]:
        df = fetch_candles(SYMBOL, tf_code, count=count)
        stats = mem.update(SYMBOL, tf_name, df)
        print(f"\n{tf_name}: {stats}")

    # Show active levels per timeframe
    last_close = fetch_candles(SYMBOL, mt5.TIMEFRAME_M15, count=2)["Close"].iloc[-1]
    print(f"\nCurrent gold price: ${last_close:.2f}")

    print(f"\n{'='*90}\nACTIVE LEVELS (by timeframe)\n{'='*90}")
    for tf_name in ["H4", "H1", "M15"]:
        active = mem.get_active(SYMBOL, tf_name)
        print(f"\n{tf_name} — {len(active)} active levels:")
        for lv in sorted(active, key=lambda x: x.price):
            marker = "▲" if lv.type in ("swing_high", "range_top") else "▼"
            distance = lv.price - last_close
            print(f"  {marker} {lv.type:<14} @ ${lv.price:>9.2f}  (touched {lv.touched_count}x, formed {lv.formed_at[:19] if lv.formed_at else 'n/a'}) [{distance:+.2f} from current]")

    print(f"\n{'='*90}\nRECENTLY BROKEN (last 24h)\n{'='*90}")
    broken = mem.get_recently_broken(SYMBOL, within_minutes=60 * 24)
    if broken:
        for lv in broken[:15]:
            print(f"  {lv.timeframe:<4} {lv.type:<14} @ ${lv.price:.2f} broken {lv.broken_direction} at {lv.broken_at[:19]}")
    else:
        print("  No levels broken in the last 24h.")

    print(f"\n{'='*90}\nNEAREST ACTIVE LEVELS TO PRICE ${last_close:.2f}\n{'='*90}")
    for tf in [None, "H4", "H1", "M15"]:
        above = mem.get_nearest(SYMBOL, last_close, "above", tf)
        below = mem.get_nearest(SYMBOL, last_close, "below", tf)
        scope = tf if tf else "any TF"
        if above or below:
            print(f"\n  Scope: {scope}")
            if above:
                print(f"    nearest ABOVE: {above.type:<14} ${above.price:.2f} (+{above.price-last_close:.2f}) on {above.timeframe}")
            if below:
                print(f"    nearest BELOW: {below.type:<14} ${below.price:.2f} ({below.price-last_close:+.2f}) on {below.timeframe}")

    print(f"\n{'='*90}\nSTATS\n{'='*90}")
    print(mem.stats(SYMBOL))

    disconnect()


if __name__ == "__main__":
    main()