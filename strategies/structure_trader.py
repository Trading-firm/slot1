"""
strategies/structure_trader.py
───────────────────────────────
Phase 5 orchestrator: wires Phases 1-4 together and enforces structural cooldown.

One public function: analyze(symbol, cfg) -> (EntrySetup | None, context_info)

The engine calls this each cycle. If it returns an EntrySetup AND cooldown
permits, the engine places dual orders (A + B).
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, List
import MetaTrader5 as mt5
import pandas as pd

from broker.mt5_connector import fetch_candles
from strategies.market_structure import find_swing_points
from strategies.mtf_analysis import (
    analyze_mtf, MTFReport, BIAS_BUY, BIAS_SELL, BIAS_RANGE, BIAS_NEUTRAL,
)
from strategies.level_memory import LevelMemory
from strategies.entry_engine import find_entry, EntrySetup


# Timeframes the structure trader uses
TF_H4  = mt5.TIMEFRAME_H4
TF_H1  = mt5.TIMEFRAME_H1
TF_M15 = mt5.TIMEFRAME_M15


@dataclass
class StructureDecision:
    setup:          Optional[EntrySetup]
    bias:           str
    reason:         str                 # why no setup (if setup is None)
    latest_swing_time: Optional[str]    # timestamp of newest confirmed M15 swing — for cooldown tracking


def latest_confirmed_swing_time(df_m15: pd.DataFrame, left: int = 5, right: int = 5) -> Optional[str]:
    """Timestamp (ISO string) of the most recent confirmed M15 swing, or None."""
    swings = find_swing_points(df_m15, left=left, right=right)
    if not swings:
        return None
    last = swings[-1]
    if "time" not in df_m15.columns:
        return str(last.idx)
    ts = df_m15["time"].iloc[last.idx]
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def analyze(symbol: str, cfg: dict) -> StructureDecision:
    """
    Fetch data, update memory, run MTF + entry engine.
    Does NOT check cooldown — engine does that before acting on the setup.
    """
    struct_cfg = cfg.get("structure", {})
    entry_cfg  = cfg.get("entry", {})

    # Fetch the three timeframes
    h4_bars  = struct_cfg.get("h4_bars",  400)
    h1_bars  = struct_cfg.get("h1_bars",  500)
    m15_bars = struct_cfg.get("m15_bars", 500)

    df_h4  = fetch_candles(symbol, TF_H4,  count=h4_bars)
    df_h1  = fetch_candles(symbol, TF_H1,  count=h1_bars)
    df_m15 = fetch_candles(symbol, TF_M15, count=m15_bars)

    if df_h4.empty or df_h1.empty or df_m15.empty:
        return StructureDecision(None, BIAS_NEUTRAL, "insufficient data on one of H4/H1/M15", None)

    # Update level memory for each timeframe
    mem = LevelMemory()
    mem.update(symbol, "H4",  df_h4,
               swing_left=struct_cfg.get("swing_left", 5),
               swing_right=struct_cfg.get("swing_right", 5),
               range_band_pct=struct_cfg.get("h4_range_band_pct", 3.0))
    mem.update(symbol, "H1",  df_h1,
               swing_left=struct_cfg.get("swing_left", 5),
               swing_right=struct_cfg.get("swing_right", 5),
               range_band_pct=struct_cfg.get("h1_range_band_pct", 2.0))
    mem.update(symbol, "M15", df_m15,
               swing_left=struct_cfg.get("swing_left", 5),
               swing_right=struct_cfg.get("swing_right", 5),
               range_band_pct=struct_cfg.get("m15_range_band_pct", 2.0))

    # MTF bias
    mtf = analyze_mtf(
        df_h4, df_h1, df_m15,
        left=struct_cfg.get("swing_left", 5),
        right=struct_cfg.get("swing_right", 5),
        min_swings=struct_cfg.get("min_swings", 3),
        range_band_pct=struct_cfg.get("m15_range_band_pct", 2.0),
        h4_range_band=struct_cfg.get("h4_range_band_pct", 3.0),
    )

    latest_swing_ts = latest_confirmed_swing_time(
        df_m15,
        left=struct_cfg.get("swing_left", 5),
        right=struct_cfg.get("swing_right", 5),
    )

    if mtf.bias == BIAS_NEUTRAL:
        return StructureDecision(None, mtf.bias, mtf.reason, latest_swing_ts)

    setup = find_entry(mtf, mem, df_m15, symbol, cfg=entry_cfg)
    if setup is None:
        return StructureDecision(None, mtf.bias, f"Bias {mtf.bias} but no entry trigger yet.", latest_swing_ts)

    # Apply min_sl_atr floor if configured — rejects trades with tiny SL
    min_sl_atr = entry_cfg.get("min_sl_atr", 0.0)
    if min_sl_atr > 0:
        from strategies.entry_engine import _atr
        atr = _atr(df_m15)
        sl_dist = abs(setup.entry_price - setup.sl)
        if sl_dist < min_sl_atr * atr:
            return StructureDecision(
                None, mtf.bias,
                f"Setup rejected: SL too tight (${sl_dist:.2f} < {min_sl_atr}*ATR ${min_sl_atr*atr:.2f})",
                latest_swing_ts,
            )

    # Apply max_sl_usd cap — reject setups where A's loss would exceed threshold
    max_sl_usd = entry_cfg.get("max_sl_usd", 0.0)
    if max_sl_usd > 0:
        lot_a = cfg.get("dual_trade", {}).get("trade_a_lot", 0.01)
        try:
            import MetaTrader5 as mt5
            si = mt5.symbol_info(symbol)
            contract = si.trade_contract_size if si else 100.0
        except Exception:
            contract = 100.0
        sl_dist = abs(setup.entry_price - setup.sl)
        a_loss_usd = sl_dist * lot_a * contract
        if a_loss_usd > max_sl_usd:
            return StructureDecision(
                None, mtf.bias,
                f"Setup rejected: A's $ loss too big (${a_loss_usd:.2f} > cap ${max_sl_usd:.2f})",
                latest_swing_ts,
            )

    return StructureDecision(setup, mtf.bias, f"Setup found: {setup.scenario}", latest_swing_ts)


def cooldown_cleared(last_exit_time_iso: Optional[str], latest_swing_ts: Optional[str]) -> bool:
    """
    Cooldown is cleared once a NEW confirmed M15 swing forms after our last exit.
    First trade ever (no prior exit) → cleared.
    """
    if last_exit_time_iso is None:
        return True
    if latest_swing_ts is None:
        return False
    return latest_swing_ts > last_exit_time_iso