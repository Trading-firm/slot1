"""
database/repository.py
───────────────────────
All database read/write operations.
The rest of the app never writes queries directly.

Collections:
  trades             — every trade opened and closed
  signals            — every signal generated
  daily_summary      — end of day performance
  bot_state          — persistent key/value store
  market_performance — per-market win rate tracking
"""

from datetime import datetime, date
from typing import Optional, List
from bson import ObjectId
from database.mongo import (
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
            "symbol":      symbol,
            "direction":   direction,
            "entry_price": entry_price,
            "sl":          sl,
            "tp":          tp,
            "lot_size":    lot_size,
            "ticket":      ticket,
            "strategy":    strategy,
            "timeframe":   timeframe,
            "rsi_at_entry":rsi,
            "atr_at_entry":atr,
            "ema_trend":   ema_trend,
            "status":      "OPEN",
            "exit_price":  None,
            "exit_reason": None,
            "pnl":         None,
            "pnl_pct":     None,
            "entry_time":  datetime.utcnow(),
            "exit_time":   None,
        }
        result = trades_col().insert_one(doc)
        doc["_id"] = result.inserted_id
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
        result = trades_col().find_one_and_update(
            {"ticket": ticket},
            {"$set": {
                "status":      "CLOSED",
                "exit_price":  exit_price,
                "exit_reason": exit_reason,
                "pnl":         pnl,
                "pnl_pct":     pnl_pct,
                "exit_time":   datetime.utcnow(),
            }},
            return_document=True,
        )
        if result:
            emoji = "✅" if pnl > 0 else "❌"
            logger.info(
                f"{emoji} Trade closed | {result['symbol']} {result['direction']} | "
                f"Reason: {exit_reason} | PnL: ${pnl:.4f} ({pnl_pct:.2f}%)"
            )
            # Update market performance stats
            PerfRepo.update(result["symbol"], pnl > 0, pnl)
        return result

    @staticmethod
    def get_open_trades(symbol: str = None) -> List[dict]:
        query = {"status": "OPEN"}
        if symbol:
            query["symbol"] = symbol
        return list(trades_col().find(query))

    @staticmethod
    def get_open_count() -> int:
        return trades_col().count_documents({"status": "OPEN"})

    @staticmethod
    def get_open_symbols() -> List[str]:
        trades = trades_col().find({"status": "OPEN"}, {"symbol": 1})
        return [t["symbol"] for t in trades]

    @staticmethod
    def get_trades_today() -> List[dict]:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return list(trades_col().find({"entry_time": {"$gte": today}}))

    @staticmethod
    def get_daily_pnl() -> float:
        trades = TradeRepo.get_trades_today()
        return sum(t["pnl"] for t in trades if t.get("pnl") is not None)

    @staticmethod
    def get_trade_by_ticket(ticket: int) -> Optional[dict]:
        return trades_col().find_one({"ticket": ticket})

    @staticmethod
    def get_last_closed_trade(symbol: str) -> Optional[dict]:
        return trades_col().find_one(
            {"symbol": symbol, "status": "CLOSED"},
            sort=[("exit_time", -1)]
        )

    @staticmethod
    def get_recent_trades(limit: int = 20) -> List[dict]:
        return list(trades_col().find(
            {"status": "CLOSED"},
            sort=[("exit_time", -1)],
            limit=limit
        ))


# ═══════════════════════════════════════════════════════════
# DAILY SUMMARY
# ═══════════════════════════════════════════════════════════
class SummaryRepo:

    @staticmethod
    def upsert() -> dict:
        today_str = date.today().isoformat()
        trades    = TradeRepo.get_trades_today()
        closed    = [t for t in trades if t["status"] == "CLOSED"]
        wins      = [t for t in closed  if t.get("pnl") and t["pnl"] > 0]
        losses    = [t for t in closed  if t.get("pnl") and t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in closed if t.get("pnl"))

        doc = {
            "date":            today_str,
            "total_trades":    len(closed),
            "winning_trades":  len(wins),
            "losing_trades":   len(losses),
            "win_rate":        round(len(wins)/len(closed)*100, 1) if closed else 0.0,
            "total_pnl":       round(total_pnl, 4),
            "best_trade":      max((t["pnl"] for t in closed if t.get("pnl")), default=0.0),
            "worst_trade":     min((t["pnl"] for t in closed if t.get("pnl")), default=0.0),
            "open_trades":     trades_col().count_documents({"status": "OPEN"}),
            "updated_at":      datetime.utcnow(),
        }
        summary_col().update_one({"date": today_str}, {"$set": doc}, upsert=True)
        return doc


# ═══════════════════════════════════════════════════════════
# BOT STATE
# ═══════════════════════════════════════════════════════════
class StateRepo:

    @staticmethod
    def set(key: str, value: str):
        state_col().update_one(
            {"key": key},
            {"$set": {"key": key, "value": value, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    @staticmethod
    def get(key: str, default: str = None) -> Optional[str]:
        doc = state_col().find_one({"key": key})
        return doc["value"] if doc else default


# ═══════════════════════════════════════════════════════════
# MARKET PERFORMANCE
# ═══════════════════════════════════════════════════════════
class PerfRepo:

    @staticmethod
    def update(symbol: str, is_win: bool, pnl: float):
        perf_col().update_one(
            {"symbol": symbol},
            {
                "$inc": {
                    "total_trades": 1,
                    "wins":         1 if is_win else 0,
                    "losses":       0 if is_win else 1,
                    "total_pnl":    pnl,
                },
                "$set": {"updated_at": datetime.utcnow()},
                "$setOnInsert": {"symbol": symbol, "created_at": datetime.utcnow()},
            },
            upsert=True,
        )

    @staticmethod
    def get_all() -> List[dict]:
        return list(perf_col().find({}, {"_id": 0}))
