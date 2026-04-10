"""
database/repository.py
───────────────────────
All database read/write operations.
The rest of the app never writes queries directly.

Firestore collections:
  trades             — every trade opened and closed  (doc ID = str(ticket))
  daily_summary      — end of day performance          (doc ID = date string)
  bot_state          — persistent key/value store      (doc ID = key)
  market_performance — per-market win rate tracking    (doc ID = symbol)
"""

from datetime import datetime, date
from typing import Optional, List
from firebase_admin import firestore as fs
from google.cloud.firestore_v1.base_query import FieldFilter
from database.firebase import (
    trades_col, summary_col, state_col, perf_col
)
from utils.logger import logger


# ═══════════════════════════════════════════════════════════
# TRADES
# ═══════════════════════════════════════════════════════════
class TradeRepo:

    @staticmethod
    def open_trade(
        symbol:     str,
        direction:  str,
        entry_price:float,
        sl:         float,
        tp:         float,
        lot_size:   float,
        ticket:     int,
        strategy:   str,
        timeframe:  str,
        rsi:        float,
        atr:        float,
        ema_trend:  float,
    ) -> dict:
        doc = {
            "symbol":       symbol,
            "direction":    direction,
            "entry_price":  entry_price,
            "sl":           sl,
            "tp":           tp,
            "lot_size":     lot_size,
            "ticket":       ticket,
            "strategy":     strategy,
            "timeframe":    timeframe,
            "rsi_at_entry": rsi,
            "atr_at_entry": atr,
            "ema_trend":    ema_trend,
            "status":       "OPEN",
            "exit_price":   None,
            "exit_reason":  None,
            "pnl":          None,
            "pnl_pct":      None,
            "entry_time":   datetime.utcnow(),
            "exit_time":    None,
        }
        trades_col().document(str(ticket)).set(doc)
        logger.info(
            f"Trade opened | {direction} {symbol} @ {entry_price:.5f} | "
            f"SL: {sl:.5f} | TP: {tp:.5f} | Lot: {lot_size} | Ticket: {ticket}"
        )
        return doc

    @staticmethod
    def close_trade(
        ticket:      int,
        exit_price:  float,
        exit_reason: str,
        pnl:         float,
        pnl_pct:     float,
    ) -> Optional[dict]:
        ref = trades_col().document(str(ticket))
        snap = ref.get()
        if not snap.exists:
            return None

        updates = {
            "status":      "CLOSED",
            "exit_price":  exit_price,
            "exit_reason": exit_reason,
            "pnl":         pnl,
            "pnl_pct":     pnl_pct,
            "exit_time":   datetime.utcnow(),
        }
        ref.update(updates)

        result = {**snap.to_dict(), **updates}
        emoji = "✅" if pnl > 0 else "❌"
        logger.info(
            f"{emoji} Trade closed | {result['symbol']} {result['direction']} | "
            f"Reason: {exit_reason} | PnL: ${pnl:.4f} ({pnl_pct:.2f}%)"
        )
        PerfRepo.update(result["symbol"], pnl > 0, pnl)
        return result

    @staticmethod
    def get_open_trades(symbol: str = None) -> List[dict]:
        query = trades_col().where(filter=FieldFilter("status", "==", "OPEN"))
        if symbol:
            query = query.where(filter=FieldFilter("symbol", "==", symbol))
        return [s.to_dict() for s in query.stream()]

    @staticmethod
    def get_open_count() -> int:
        return len(TradeRepo.get_open_trades())

    @staticmethod
    def get_open_symbols() -> List[str]:
        trades = trades_col().where(filter=FieldFilter("status", "==", "OPEN")).stream()
        return [s.to_dict()["symbol"] for s in trades]

    @staticmethod
    def get_trades_today() -> List[dict]:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        docs = trades_col().where(filter=FieldFilter("entry_time", ">=", today)).stream()
        return [s.to_dict() for s in docs]

    @staticmethod
    def get_daily_pnl() -> float:
        trades = TradeRepo.get_trades_today()
        return sum(t["pnl"] for t in trades if t.get("pnl") is not None)

    @staticmethod
    def get_trade_by_ticket(ticket: int) -> Optional[dict]:
        snap = trades_col().document(str(ticket)).get()
        return snap.to_dict() if snap.exists else None

    @staticmethod
    def get_last_closed_trade(symbol: str) -> Optional[dict]:
        docs = (
            trades_col()
            .where(filter=FieldFilter("symbol", "==", symbol))
            .where(filter=FieldFilter("status", "==", "CLOSED"))
            .order_by("exit_time", direction=fs.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        results = [s.to_dict() for s in docs]
        return results[0] if results else None

    @staticmethod
    def get_recent_trades(limit: int = 20) -> List[dict]:
        docs = (
            trades_col()
            .where(filter=FieldFilter("status", "==", "CLOSED"))
            .order_by("exit_time", direction=fs.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [s.to_dict() for s in docs]


# ═══════════════════════════════════════════════════════════
# DAILY SUMMARY
# ═══════════════════════════════════════════════════════════
class SummaryRepo:

    @staticmethod
    def upsert() -> dict:
        today_str = date.today().isoformat()
        trades    = TradeRepo.get_trades_today()
        closed    = [t for t in trades if t["status"] == "CLOSED"]
        wins      = [t for t in closed if t.get("pnl") and t["pnl"] > 0]
        losses    = [t for t in closed if t.get("pnl") and t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in closed if t.get("pnl"))

        doc = {
            "date":           today_str,
            "total_trades":   len(closed),
            "winning_trades": len(wins),
            "losing_trades":  len(losses),
            "win_rate":       round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
            "total_pnl":      round(total_pnl, 4),
            "best_trade":     max((t["pnl"] for t in closed if t.get("pnl")), default=0.0),
            "worst_trade":    min((t["pnl"] for t in closed if t.get("pnl")), default=0.0),
            "open_trades":    TradeRepo.get_open_count(),
            "updated_at":     datetime.utcnow(),
        }
        summary_col().document(today_str).set(doc)
        return doc


# ═══════════════════════════════════════════════════════════
# BOT STATE
# ═══════════════════════════════════════════════════════════
class StateRepo:

    @staticmethod
    def set(key: str, value: str):
        state_col().document(key).set({
            "key":        key,
            "value":      value,
            "updated_at": datetime.utcnow(),
        })

    @staticmethod
    def get(key: str, default: str = None) -> Optional[str]:
        snap = state_col().document(key).get()
        return snap.to_dict()["value"] if snap.exists else default


# ═══════════════════════════════════════════════════════════
# MARKET PERFORMANCE
# ═══════════════════════════════════════════════════════════
class PerfRepo:

    @staticmethod
    def update(symbol: str, is_win: bool, pnl: float):
        ref  = perf_col().document(symbol)
        snap = ref.get()

        if snap.exists:
            ref.update({
                "total_trades": fs.Increment(1),
                "wins":         fs.Increment(1 if is_win else 0),
                "losses":       fs.Increment(0 if is_win else 1),
                "total_pnl":    fs.Increment(pnl),
                "updated_at":   datetime.utcnow(),
            })
        else:
            ref.set({
                "symbol":       symbol,
                "total_trades": 1,
                "wins":         1 if is_win else 0,
                "losses":       0 if is_win else 1,
                "total_pnl":    pnl,
                "created_at":   datetime.utcnow(),
                "updated_at":   datetime.utcnow(),
            })

    @staticmethod
    def get_all() -> List[dict]:
        return [s.to_dict() for s in perf_col().stream()]