"""
risk/manager.py
────────────────
Risk management engine.
All trade decisions pass through here before execution.

Rules enforced:
  1. Max open trades (one per market maximum)
  2. No duplicate symbol trades
  3. Max daily loss stop
  4. Minimum lot size enforcement
  5. TP bias to favour hitting TP over SL
"""

from datetime import datetime, timedelta, timezone
from config.settings import settings
from database.repository import TradeRepo
from utils.logger import logger


class RiskManager:

    def __init__(self):
        self.max_open    = settings.MAX_OPEN_TRADES
        self.max_dd      = settings.MAX_DAILY_LOSS
        self.risk_pct    = settings.RISK_PER_TRADE
        self.min_lot     = settings.MIN_LOT_SIZE
        self.max_lot     = settings.MAX_LOT_SIZE
        # Cooldown periods in minutes
        self.tp_cooldown = 60   # 1 hour after TP
        self.sl_cooldown = 240  # 4 hours after SL

    def can_trade(self, symbol: str, balance: float) -> tuple:
        """
        Returns (True, "") if trade is allowed.
        Returns (False, reason) if blocked.
        """
        # Rule 1 — Max open trades
        # Reserve slots based on what this market could place:
        # Boom 1000 can place up to 10 orders; all others place 1.
        if symbol == "Boom 1000 Index":
            if balance >= 500:
                slots_needed = 10
            elif balance >= 200:
                slots_needed = 5
            elif balance >= 100:
                slots_needed = 3
            else:
                slots_needed = 1
        else:
            slots_needed = 1

        open_count = TradeRepo.get_open_count()
        if open_count + slots_needed > self.max_open:
            reason = f"Max trades reached — need {slots_needed} free slot(s) ({open_count}/{self.max_open})"
            logger.warning(f"[{symbol}] Blocked — {reason}")
            return False, reason

        # Rule 2 — Allow only one "set" of scaling trades at a time
        open_symbols = TradeRepo.get_open_symbols()
        if symbol in open_symbols:
            reason = f"Already have active position(s) on {symbol}"
            logger.warning(f"[{symbol}] Blocked — {reason}")
            return False, reason

        # Rule 3 — Daily loss limit stop
        daily_pnl = TradeRepo.get_daily_pnl()
        max_loss  = -(balance * self.max_dd)
        if daily_pnl <= max_loss:
            reason = f"Daily loss limit hit — PnL ${daily_pnl:.2f} <= limit ${max_loss:.2f}"
            logger.warning(f"[{symbol}] Blocked — {reason}")
            return False, reason

        # Rule 4 — Sentiment-Based Cooldown (Global Pause)
        # If the last 3 trades across the entire bot were losses, pause all trading.
        recent_trades = TradeRepo.get_recent_trades(limit=3)
        if len(recent_trades) >= 3:
            all_losses = all(t.get("pnl", 0) <= 0 for t in recent_trades)
            if all_losses:
                last_exit = max(t["exit_time"] for t in recent_trades if t.get("exit_time"))
                wait_until = last_exit + timedelta(hours=4)
                now = datetime.now(timezone.utc)
                if now < wait_until:
                    diff = wait_until - now
                    hours_left = round(diff.total_seconds() / 3600, 1)
                    reason = f"Sentiment Pause — 3 consecutive losses across markets. {hours_left}h remaining"
                    logger.warning(f"[{symbol}] Blocked — {reason}")
                    return False, reason

        # Rule 5 — Market-Specific Cooldown
        last_trade = TradeRepo.get_last_closed_trade(symbol)
        if last_trade and last_trade.get("exit_time"):
            exit_time = last_trade["exit_time"]
            reason    = last_trade.get("exit_reason", "SL")
            
            # 8-hour wait after a Hard SL (Market trend might be changing)
            # 2-hour wait after a Trailing Stop (Wait for next pullback)
            # 1-hour wait after a TP (Wait for next pullback)
            if "SL" in reason:
                cooldown_mins = 480 # 8 hours
            elif "Trail" in reason or "Break-Even" in reason:
                cooldown_mins = 120 # 2 hours
            else:
                cooldown_mins = 60  # 1 hour
                
            wait_until    = exit_time + timedelta(minutes=cooldown_mins)
            
            now = datetime.now(timezone.utc)
            if now < wait_until:
                diff = wait_until - now
                mins_left = round(diff.total_seconds() / 60)
                msg = f"In cooldown after {reason} — {mins_left}m remaining"
                logger.warning(f"[{symbol}] Blocked — {msg}")
                return False, msg

        return True, ""

    def validate_lot(self, lot_size: float, symbol_min: float) -> float:
        """Clamp lot size between the symbol minimum and the global maximum."""
        return max(symbol_min, min(lot_size, self.max_lot))

    def print_status(self, balance: float):
        open_count = TradeRepo.get_open_count()
        daily_pnl  = TradeRepo.get_daily_pnl()
        max_loss   = balance * self.max_dd
        logger.info(
            f"Risk Status | Open: {open_count}/{self.max_open} | "
            f"Daily PnL: ${daily_pnl:.4f} | "
            f"Max Loss: -${max_loss:.4f} | "
            f"Balance: ${balance:.2f}"
        )
