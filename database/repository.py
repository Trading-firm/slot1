"""
database/repository.py
──────────────────────
All database read/write operations for MongoDB.
The rest of the app never writes queries directly —
it always calls functions from here.
"""

from datetime import datetime, date
from typing import Optional, List
from bson import ObjectId
from database.models import (
    trades_col, signals_col, daily_summary_col, bot_state_col
)
from utils.logger import logger


class TradeRepository:
    """Handles all trade-related database operations."""

    @staticmethod
    def create_trade(
        pair: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: float,
        broker_order_id,
        mode: str,
        timeframe: str,
        strategy: str = "EMA_RSI",
    ) -> dict:
        trade = {
            "pair":        pair,
            "direction":   direction,
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "quantity":    quantity,
            "broker_order_id": broker_order_id,
            "mode":        mode,
            "timeframe":   timeframe,
            "strategy":    strategy,
            "status":      "OPEN",
            "exit_pending_count": 0,
            "exit_pending_reason": None,
            "exit_price":  None,
            "exit_reason": None,
            "pnl":         None,
            "pnl_pct":     None,
            "entry_time":  datetime.utcnow(),
            "exit_time":   None,
        }
        result = trades_col().insert_one(trade)
        trade["_id"] = result.inserted_id
        logger.info(
            f"Trade created: {direction} {pair} @ {entry_price:.5f} | "
            f"SL: {stop_loss:.5f} | TP: {take_profit:.5f} | ID: {result.inserted_id}"
        )
        return trade

    @staticmethod
    def close_trade(
        trade_id,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
    ) -> Optional[dict]:
        if isinstance(trade_id, str):
            trade_id = ObjectId(trade_id)

        result = trades_col().find_one_and_update(
            {"_id": trade_id},
            {
                "$set": {
                    "status":      "CLOSED",
                    "exit_price":  exit_price,
                    "exit_reason": exit_reason,
                    "pnl":         pnl,
                    "pnl_pct":     pnl_pct,
                    "exit_time":   datetime.utcnow(),
                },
                "$unset": {
                    "exit_pending_count": "",
                    "exit_pending_reason": "",
                },
            },
            return_document=True,
        )
        if result:
            # Also update the linked signal if exists
            try:
                outcome = "WIN" if pnl > 0 else "LOSS"
                signals_col().update_one(
                    {"trade_id": str(trade_id)},
                    {
                        "$set": {
                            "pnl": pnl,
                            "pnl_pct": pnl_pct,
                            "outcome": outcome,
                            "exit_reason": exit_reason
                        }
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to update linked signal for trade {trade_id}: {e}")

            logger.info(
                f"Trade closed: {result['pair']} {result['direction']} | "
                f"Reason: {exit_reason} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)"
            )
        return result

    @staticmethod
    def bump_exit_pending(trade_id, reason: str) -> int:
        if isinstance(trade_id, str):
            trade_id = ObjectId(trade_id)

        result = trades_col().find_one_and_update(
            {"_id": trade_id, "status": "OPEN"},
            {
                "$inc": {"exit_pending_count": 1},
                "$set": {"exit_pending_reason": reason},
            },
            return_document=True,
        )
        try:
            return int(result.get("exit_pending_count", 0)) if result else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def reset_exit_pending(trade_id):
        if isinstance(trade_id, str):
            trade_id = ObjectId(trade_id)

        trades_col().update_one(
            {"_id": trade_id, "status": "OPEN"},
            {"$set": {"exit_pending_count": 0, "exit_pending_reason": None}},
        )

    @staticmethod
    def get_open_trades(pair: Optional[str] = None, strategy: Optional[str] = None) -> List[dict]:
        query = {"status": "OPEN"}
        if pair:
            query["pair"] = pair
        if strategy:
            query["strategy"] = strategy
        return list(trades_col().find(query))

    @staticmethod
    def get_open_trade_count() -> int:
        return trades_col().count_documents({"status": "OPEN"})

    @staticmethod
    def get_trades_today() -> List[dict]:
        """
        Get trades that were either:
        1. Opened today (entry_time >= today)
        2. Closed today (exit_time >= today)
        """
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return list(trades_col().find({
            "$or": [
                {"entry_time": {"$gte": today}},
                {"exit_time": {"$gte": today}}
            ]
        }))

    @staticmethod
    def get_daily_pnl() -> float:
        """
        Calculate realized PnL for trades closed today.
        """
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        # We only care about trades CLOSED today for the Daily Loss Limit
        trades = list(trades_col().find({
            "status": "CLOSED",
            "exit_time": {"$gte": today}
        }))
        return sum(t["pnl"] for t in trades if t.get("pnl") is not None)


class SignalRepository:
    """Handles all signal-related database operations."""

    @staticmethod
    def create_signal(
        pair: str,
        signal_type: str,
        timeframe: str,
        close_price: float,
        ema_fast: Optional[float] = None,
        ema_slow: Optional[float] = None,
        rsi: Optional[float] = None,
        atr: Optional[float] = None,
        bb_upper: Optional[float] = None,
        bb_lower: Optional[float] = None,
        acted_on: bool = False,
        reason_skipped: Optional[str] = None,
        strategy: str = "EMA_RSI",
        metadata: Optional[dict] = None,
        trade_id: Optional[str] = None,
    ) -> dict:
        signal = {
            "pair":           pair,
            "signal_type":    signal_type,
            "timeframe":      timeframe,
            "strategy":       strategy,
            "ema_fast":       ema_fast,
            "ema_slow":       ema_slow,
            "rsi":            rsi,
            "atr":            atr,
            "bb_upper":       bb_upper,
            "bb_lower":       bb_lower,
            "close_price":    close_price,
            "acted_on":       acted_on,
            "reason_skipped": reason_skipped,
            "metadata":       metadata or {},
            "created_at":     datetime.utcnow(),
            "trade_id":       trade_id,
        }
        result = signals_col().insert_one(signal)
        signal["_id"] = result.inserted_id
        logger.debug(f"Signal logged: {signal_type} {pair} | acted={acted_on}")
        return signal


class DailySummaryRepository:
    """Handles daily performance summary."""

    @staticmethod
    def upsert_summary() -> dict:
        today_str   = date.today().isoformat()
        trades      = TradeRepository.get_trades_today()
        closed      = [t for t in trades if t["status"] == "CLOSED"]
        winning     = [t for t in closed if t.get("pnl") and t["pnl"] > 0]
        losing      = [t for t in closed if t.get("pnl") and t["pnl"] <= 0]
        total_pnl   = sum(t["pnl"] for t in closed if t.get("pnl"))

        summary = {
            "date":           today_str,
            "total_trades":   len(closed),
            "winning_trades": len(winning),
            "losing_trades":  len(losing),
            "win_rate":       (len(winning) / len(closed) * 100) if closed else 0.0,
            "total_pnl":      total_pnl,
            "best_trade_pnl": max((t["pnl"] for t in closed if t.get("pnl")), default=0.0),
            "worst_trade_pnl":min((t["pnl"] for t in closed if t.get("pnl")), default=0.0),
            "updated_at":     datetime.utcnow(),
        }

        daily_summary_col().update_one(
            {"date": today_str},
            {"$set": summary},
            upsert=True,
        )

        logger.info(
            f"Daily summary updated | Date: {today_str} | "
            f"Trades: {len(closed)} | PnL: ${total_pnl:.2f} | "
            f"Win Rate: {summary['win_rate']:.1f}%"
        )
        return summary


class BotStateRepository:
    """Persistent key-value store for bot state."""

    @staticmethod
    def set(key: str, value: str):
        bot_state_col().update_one(
            {"key": key},
            {"$set": {"key": key, "value": value, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    @staticmethod
    def get(key: str, default: Optional[str] = None) -> Optional[str]:
        doc = bot_state_col().find_one({"key": key})
        return doc["value"] if doc else default
