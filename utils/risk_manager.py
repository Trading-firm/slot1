"""
utils/risk_manager.py
─────────────────────
Risk management engine.
Checks every potential trade against risk rules before execution.

Rules enforced:
  1. Max open trades limit
  2. Max daily loss limit
  3. No duplicate trades on same pair
  4. Position size calculation
"""

from config.settings import settings
from utils.logger import logger
from database.repository import TradeRepository, BotStateRepository
from datetime import datetime


class RiskManager:

    def __init__(self):
        self.max_open_trades = settings.MAX_OPEN_TRADES
        self.max_daily_loss  = settings.MAX_DAILY_LOSS
        self.risk_per_trade  = settings.RISK_PER_TRADE

    def can_trade(self, pair: str, balance: float, strategy: str = None) -> tuple:
        """
        Returns (True, "", metrics) if trade is allowed,
        or (False, reason, metrics) if blocked.
        metrics contains debug info like daily_pnl, open_trades, etc.
        """
        # Rule 1: Max open trades
        # If max_open_trades is 0 or very large (e.g. > 99), we consider it disabled/unlimited
        open_count = TradeRepository.get_open_trade_count()
        metrics = {
            "open_trades": open_count,
            "max_open_trades": self.max_open_trades,
            "daily_pnl": 0.0,
            "max_daily_loss": 0.0
        }

        if 0 < self.max_open_trades < 100:
            if open_count >= self.max_open_trades:
                reason = f"Max open trades reached ({open_count}/{self.max_open_trades})"
                logger.warning(f"[{pair}] Trade blocked — {reason}")
                return False, reason, metrics
        
        # Rule 2: Max daily loss
        today_key = f"daily_start_balance:{datetime.utcnow().date().isoformat()}"
        stored = BotStateRepository.get(today_key)
        try:
            start_balance = float(stored) if stored is not None else float(balance)
        except (TypeError, ValueError):
            start_balance = float(balance)

        if stored is None:
            BotStateRepository.set(today_key, f"{start_balance}")

        daily_pnl = float(balance) - float(start_balance)
        max_loss_amount = float(getattr(settings, "MAX_DAILY_LOSS_USD", 0.0) or 0.0)
        if max_loss_amount > 0:
            max_loss = -max_loss_amount
        else:
            max_loss = -(float(start_balance) * float(self.max_daily_loss))
        
        metrics["daily_pnl"] = daily_pnl
        metrics["max_daily_loss"] = abs(max_loss)
        metrics["start_balance"] = start_balance
        metrics["current_balance"] = float(balance)

        if daily_pnl <= max_loss:
            reason = (
                f"Daily loss limit hit — Balance change ${daily_pnl:.2f} <= "
                f"-${abs(max_loss):.2f} (Start ${start_balance:.2f} → Now ${float(balance):.2f})"
            )
            logger.warning(f"[{pair}] Trade blocked — {reason}")
            return False, reason, metrics

        # Rule 3: No duplicate on same pair/strategy
        # We enforce ONE trade per pair to avoid conflicting signals (e.g. BUY then SELL).
        # We ignore the strategy parameter here to check globally for the pair.
        open_on_pair = TradeRepository.get_open_trades(pair=pair)
        if open_on_pair:
            reason = f"Already have an open trade on {pair} (enforcing one trade per pair)"
            logger.warning(f"[{pair}] Trade blocked — {reason}")
            return False, reason, metrics

        logger.debug(f"[{pair}] Risk checks passed.")
        return True, "", metrics

    def check_exit(self, trade: dict, ticker_or_price) -> tuple:
        direction = trade["direction"]

        try:
            stop_loss = float(trade["stop_loss"])
            take_profit = float(trade["take_profit"])
        except (TypeError, ValueError, KeyError):
            return False, "", None

        bid = None
        ask = None
        last = None

        if isinstance(ticker_or_price, dict):
            try:
                bid = float(ticker_or_price.get("bid")) if ticker_or_price.get("bid") is not None else None
            except (TypeError, ValueError):
                bid = None
            try:
                ask = float(ticker_or_price.get("ask")) if ticker_or_price.get("ask") is not None else None
            except (TypeError, ValueError):
                ask = None
            try:
                last = float(ticker_or_price.get("last")) if ticker_or_price.get("last") is not None else None
            except (TypeError, ValueError):
                last = None
        else:
            try:
                last = float(ticker_or_price)
            except (TypeError, ValueError):
                last = None

        if direction == "BUY":
            check_price = bid if bid is not None else (last if last is not None else ask)
            if check_price is None:
                return False, "", None
            if check_price <= stop_loss:
                return True, f"SL (bid {check_price:.5f} <= {stop_loss:.5f})", check_price
            if check_price >= take_profit:
                return True, f"TP (bid {check_price:.5f} >= {take_profit:.5f})", check_price
        elif direction == "SELL":
            check_price = ask if ask is not None else (last if last is not None else bid)
            if check_price is None:
                return False, "", None
            if check_price >= stop_loss:
                return True, f"SL (ask {check_price:.5f} >= {stop_loss:.5f})", check_price
            if check_price <= take_profit:
                return True, f"TP (ask {check_price:.5f} <= {take_profit:.5f})", check_price

        return False, "", None

    def calculate_pnl(self, trade: dict, exit_price: float) -> tuple:
        """Calculate P&L for a closing trade."""
        entry = trade["entry_price"]
        qty   = trade["quantity"]

        if trade["direction"] == "BUY":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        cost    = entry * qty
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0

        return round(pnl, 4), round(pnl_pct, 4)

    def print_risk_summary(self, balance: float):
        """Log current risk status."""
        open_count = TradeRepository.get_open_trade_count()
        today_key = f"daily_start_balance:{datetime.utcnow().date().isoformat()}"
        stored = BotStateRepository.get(today_key)
        try:
            start_balance = float(stored) if stored is not None else float(balance)
        except (TypeError, ValueError):
            start_balance = float(balance)

        if stored is None:
            BotStateRepository.set(today_key, f"{start_balance}")

        daily_pnl = float(balance) - float(start_balance)
        max_loss_amount = float(getattr(settings, "MAX_DAILY_LOSS_USD", 0.0) or 0.0)
        if max_loss_amount > 0:
            max_loss = max_loss_amount
        else:
            max_loss = float(start_balance) * float(self.max_daily_loss)

        logger.info(
            f"Risk Summary | Open: {open_count}/{self.max_open_trades} | "
            f"Daily PnL: ${daily_pnl:.2f} | Max Loss: -${max_loss:.2f} | "
            f"Balance: ${balance:.2f} | Start: ${start_balance:.2f}"
        )
