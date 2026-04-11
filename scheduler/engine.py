"""
scheduler/engine.py
────────────────────
Main trading engine.
"""

from broker.mt5_connector import (
    connect, disconnect, get_balance, fetch_candles,
    get_open_positions, place_order,
    get_symbol_info,
)
from strategies.signal_engine import generate_signal
from risk.manager import RiskManager
from database.firebase import init_db
from database.repository import TradeRepo, SummaryRepo, StateRepo
from config.markets import MARKETS
from config.settings import settings
from utils.logger import logger
from datetime import datetime, timezone
import MetaTrader5 as mt5


class TradingEngine:

    def __init__(self):
        logger.info("Initialising Unified Trading Engine...")
        init_db()
        self.risk = RiskManager()
        logger.info(
            f"Engine ready | Markets: {len(MARKETS)} | "
            f"Risk/Trade: {settings.RISK_PER_TRADE*100:.1f}% | "
            f"Max Trades: {settings.MAX_OPEN_TRADES}"
        )

    def run_cycle(self):
        logger.info("=" * 70)
        logger.info(f"CYCLE START | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info("=" * 70)

        if not connect():
            logger.error("MT5 connection failed — skipping cycle")
            return

        try:
            balance = get_balance()
            if balance <= 0:
                logger.error("Zero balance — stopping")
                return

            self.risk.print_status(balance)
            StateRepo.set("last_cycle", datetime.now(timezone.utc).isoformat())
            StateRepo.set("balance",    str(round(balance, 2)))

            self._sync_positions()

            for symbol, cfg in MARKETS.items():
                try:
                    self._process_market(symbol, cfg, balance)
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}", exc_info=True)

            summary = SummaryRepo.upsert()
            logger.info(
                f"Daily Summary | Trades: {summary['total_trades']} | "
                f"PnL: ${summary['total_pnl']:.4f} | "
                f"Win Rate: {summary['win_rate']}%"
            )

        except Exception as e:
            logger.error(f"Critical engine error: {e}", exc_info=True)
        finally:
            disconnect()

        logger.info("CYCLE COMPLETE")
        logger.info("=" * 70)

    def _sync_positions(self):
        mt5_positions = get_open_positions()
        mt5_tickets   = {p["ticket"] for p in mt5_positions}
        db_open       = TradeRepo.get_open_trades()

        synced = 0
        for trade in db_open:
            ticket = trade.get("ticket")
            if ticket is None:
                continue

            if ticket not in mt5_tickets:
                # Position closed on MT5 — record it in DB
                self._record_mt5_close(trade)
                synced += 1
            else:
                # Position still open — check if we should exit early
                if self._should_early_exit(trade):
                    from broker.mt5_connector import close_order
                    # Capture close price before sending the order
                    tick = mt5.symbol_info_tick(trade["symbol"])
                    close_price = (
                        tick.bid if trade["direction"] == "BUY" else tick.ask
                    ) if tick else None

                    if close_order(ticket, trade["symbol"], trade["direction"], trade["lot_size"]):
                        logger.info(f"[{trade['symbol']}] EARLY EXIT: Signal Invalidated or Reversed")
                        # Record close immediately with the captured price
                        self._record_manual_close(trade, close_price, "Early Exit")
                        continue  # Skip trailing-stop logic for this trade

                pos = next(p for p in mt5_positions if p["ticket"] == ticket)
                self._handle_trailing_stop(trade, pos)

        if synced:
            logger.info(f"Synced {synced} closed position(s) from MT5")

    def _should_early_exit(self, trade: dict) -> bool:
        """
        Returns True if the trade should be closed before hitting TP or SL.
        Triggers if:
        1. Signal Reverses: BUY trade but current signal is SELL.
        2. Structural Invalidation: Trend flipped or OB structure broken.
        """
        from strategies.signal_engine import check_invalidation
        symbol = trade["symbol"]
        cfg    = MARKETS.get(symbol)
        if not cfg:
            return False

        df = fetch_candles(symbol, cfg["timeframe"], count=100)
        if df.empty:
            return False

        invalid, reason = check_invalidation(df, trade, cfg)
        if invalid:
            logger.info(f"[{symbol}] INVALIDATION: {reason}. Closing trade.")
            return True

        signal = generate_signal(df, cfg)
        if trade["direction"] == "BUY" and signal.base_signal == "SELL":
            logger.info(f"[{symbol}] REVERSAL: Signal flipped to SELL. Closing BUY.")
            return True
        if trade["direction"] == "SELL" and signal.base_signal == "BUY":
            logger.info(f"[{symbol}] REVERSAL: Signal flipped to BUY. Closing SELL.")
            return True

        return False

    def _handle_trailing_stop(self, trade: dict, pos: dict):
        """
        Break-Even management: moves SL to entry once profit reaches 1x ATR.
        """
        from broker.mt5_connector import update_stops
        symbol = trade["symbol"]

        atr_entry = trade.get("atr_at_entry", 0)
        if atr_entry <= 0:
            return

        current_sl  = pos["sl"]
        current_tp  = pos["tp"]
        entry_price = trade["entry_price"]

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return

        if trade["direction"] == "BUY":
            current_price = tick.bid
            profit_dist   = current_price - entry_price

            # Move SL to entry once profit >= 1x ATR (only if SL still below entry)
            if profit_dist >= atr_entry and current_sl < entry_price:
                update_stops(trade["ticket"], symbol, entry_price, current_tp)
                logger.info(f"[{symbol}] BREAK-EVEN: SL moved to entry {entry_price:.5f}")

        else:  # SELL
            current_price = tick.ask
            profit_dist   = entry_price - current_price

            # Move SL to entry once profit >= 1x ATR (only if SL still above entry)
            if profit_dist >= atr_entry and current_sl > entry_price:
                update_stops(trade["ticket"], symbol, entry_price, current_tp)
                logger.info(f"[{symbol}] BREAK-EVEN: SL moved to entry {entry_price:.5f}")

    def _record_mt5_close(self, trade: dict):
        """Record a trade that was closed on MT5 (hit TP, SL, or closed manually)."""
        history     = mt5.history_deals_get(position=trade["ticket"])
        exit_price  = None
        exit_reason = "UNKNOWN"

        if history:
            for deal in history:
                if deal.entry == 1:  # entry type 1 = exit deal
                    exit_price = deal.price
                    if deal.profit > 0:
                        exit_reason = "TP"
                    elif deal.profit < 0:
                        exit_reason = "SL"
                    else:
                        exit_reason = "MANUAL"
                    break

        if exit_price is None:
            # History lookup failed — use entry price to avoid fake PnL
            logger.warning(
                f"[{trade['symbol']}] Exit deal not found for ticket {trade['ticket']} "
                f"— recording at entry price with UNKNOWN reason"
            )
            exit_price  = trade["entry_price"]
            exit_reason = "UNKNOWN"

        self._write_close(trade, exit_price, exit_reason)

    def _record_manual_close(self, trade: dict, close_price: float | None, reason: str):
        """Record a close that we initiated ourselves (early exit)."""
        if close_price is None:
            # Tick was unavailable — fall back to entry price
            logger.warning(
                f"[{trade['symbol']}] Could not capture close price for early exit "
                f"ticket {trade['ticket']} — recording at entry price"
            )
            close_price = trade["entry_price"]
        self._write_close(trade, close_price, reason)

    def _write_close(self, trade: dict, exit_price: float, exit_reason: str):
        """Compute PnL and persist the closed trade to the database."""
        entry   = trade["entry_price"]
        qty     = trade["lot_size"]
        pnl     = (exit_price - entry) * qty if trade["direction"] == "BUY" \
                  else (entry - exit_price) * qty
        cost    = entry * qty
        pnl_pct = round(pnl / cost * 100, 4) if cost > 0 else 0

        TradeRepo.close_trade(
            ticket      = trade["ticket"],
            exit_price  = exit_price,
            exit_reason = exit_reason,
            pnl         = round(pnl, 4),
            pnl_pct     = pnl_pct,
        )

        new_balance = get_balance()
        if new_balance > 0:
            StateRepo.set("balance", str(round(new_balance, 2)))
            logger.info(f"Balance updated after trade close: ${new_balance:.2f}")

    def _process_market(self, symbol: str, cfg: dict, balance: float):
        logger.info(f"── Analysing {symbol} [{cfg['tf_name']}] ──")

        df = fetch_candles(symbol, cfg["timeframe"], count=300)
        if df.empty:
            logger.warning(f"[{symbol}] No candle data returned")
            return

        # Fetch higher timeframe data for trend confirmation if configured
        htf_tf = cfg.get("filters", {}).get("htf_timeframe")
        htf_df = None
        if htf_tf:
            htf_df = fetch_candles(symbol, htf_tf, count=250)
            if htf_df.empty:
                logger.warning(f"[{symbol}] No H1 data — skipping HTF filter")
                htf_df = None

        signal = generate_signal(df, cfg, htf_df=htf_df)

        if signal.direction == "NONE":
            if signal.base_signal != "NONE":
                logger.warning(
                    f"[{symbol}] Base signal {signal.base_signal} blocked | "
                    f"Reason: {signal.reason} | RSI: {signal.rsi} | "
                    f"EMA200: {signal.ema_trend:.5f} | Close: {signal.close:.5f}"
                )
            else:
                logger.info(f"[{symbol}] No signal | {signal.reason}")
            return

        logger.info(
            f"[{symbol}] SIGNAL: {signal.direction} | "
            f"RSI: {signal.rsi} | Close: {signal.close:.5f} | "
            f"EMA200: {signal.ema_trend:.5f}"
        )

        can_trade, block_reason = self.risk.can_trade(symbol, balance)
        if not can_trade:
            logger.warning(f"[{symbol}] Trade blocked by risk — {block_reason}")
            return

        # ─── Position Sizing ──────────────────────────────
        # Use the market's minimum lot size as a static fixed lot per order.
        # Each TP order gets exactly min_lot — increase min_lot in markets.py to scale up.
        sym_info    = get_symbol_info(symbol)
        sym_min_lot = cfg.get("min_lot")
        if sym_min_lot is None:
            sym_min_lot = sym_info.volume_min if sym_info else settings.MIN_LOT_SIZE

        lot_part = sym_min_lot

        # ─── Scaling-Out: 3 separate orders at min_lot each ───────
        tps = [signal.tp1, signal.tp2, signal.tp3]

        logger.info(
            f"[{symbol}] Placing {len(tps)} order(s) | "
            f"Lot: {lot_part} each | SL: {signal.sl:.5f} | "
            f"TPs: {[round(t, 5) for t in tps]}"
        )

        for i, tp in enumerate(tps, 1):
            order = place_order(
                symbol    = symbol,
                direction = signal.direction,
                lot_size  = lot_part,
                sl        = signal.sl,
                tp        = tp,
                comment   = f"UB_{cfg['strategy']}_TP{i}",
            )

            if not order:
                logger.error(f"[{symbol}] Order placement FAILED for TP{i}")
                continue

            TradeRepo.open_trade(
                symbol      = symbol,
                direction   = signal.direction,
                entry_price = order["price"],
                sl          = signal.sl,
                tp          = tp,
                lot_size    = lot_part,
                ticket      = order["ticket"],
                strategy    = cfg["strategy"],
                timeframe   = cfg["tf_name"],
                rsi         = signal.rsi,
                atr         = signal.atr,
                ema_trend   = signal.ema_trend,
            )

            logger.info(
                f"Trade executed ({i}/{len(tps)}) | {signal.direction} {symbol} | "
                f"Lot: {lot_part} | TP: {tp:.5f} | Ticket: {order['ticket']}"
            )
