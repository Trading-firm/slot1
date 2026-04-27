"""
scheduler/engine.py
────────────────────
Live trading engine for the EMA trend-follower strategy.

Per cycle:
  1. Connect to MT5; balance + risk-status snapshot.
  2. Sync open positions: close DB rows for trades no longer on broker;
     check trend-flip exit on still-open trades.
  3. For each market:
     - Skip if a position is already open on this symbol (single trade per symbol).
     - Skip if cooldown bars have not elapsed since last exit.
     - Run trend_follower.find_entry on M15.
     - Risk-manager veto.
     - Place a single market order; persist to Firestore.
"""

from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

from broker.mt5_connector import (
    connect, disconnect, fetch_candles, get_balance,
    get_open_positions, place_order, close_order,
    get_symbol_info, resolve_symbol,
)
from strategies.trend_follower import find_entry, trend_flipped
from risk.manager import RiskManager
from database.firebase import init_db
from database.repository import TradeRepo, SummaryRepo, StateRepo
from config.markets import MARKETS
from config.settings import settings
from utils.logger import logger


class TradingEngine:

    def __init__(self):
        logger.info("Initialising Trend-Follower Engine...")
        init_db()
        self.risk = RiskManager()
        logger.info(
            f"Engine ready | Markets: {len(MARKETS)} | "
            f"Risk/Trade: {settings.RISK_PER_TRADE*100:.1f}% | "
            f"Max Trades: {settings.MAX_OPEN_TRADES}"
        )

    # ── Cycle entry point ───────────────────────────────────────────────────
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

            for market_key, cfg in MARKETS.items():
                try:
                    self._process_market(market_key, cfg, balance)
                except Exception as e:
                    logger.error(f"Error processing {market_key}: {e}", exc_info=True)

            summary = SummaryRepo.upsert()
            logger.info(
                f"Daily Summary | Trades: {summary['total_trades']} | "
                f"PnL: ${summary['total_pnl']:.4f} | WR: {summary['win_rate']}%"
            )
        except Exception as e:
            logger.error(f"Critical engine error: {e}", exc_info=True)
        finally:
            disconnect()

        logger.info("CYCLE COMPLETE")
        logger.info("=" * 70)

    # ── Position sync + trend-flip exit ─────────────────────────────────────
    def _sync_positions(self):
        mt5_positions = get_open_positions() or []
        mt5_tickets   = {p["ticket"] for p in mt5_positions}
        db_open       = TradeRepo.get_open_trades()

        synced = 0
        for trade in db_open:
            ticket = trade.get("ticket")
            if ticket is None:
                continue

            if ticket not in mt5_tickets:
                # Position closed on MT5 (broker SL/TP or manual) — record it.
                self._record_mt5_close(trade)
                synced += 1
                continue

            # Still open: check trend-flip early exit.
            symbol = trade["symbol"]
            cfg = MARKETS.get(symbol) or {}
            entry_cfg = cfg.get("entry", {})
            df = fetch_candles(symbol, mt5.TIMEFRAME_M15, count=250)
            if df.empty or len(df) < 210:
                continue

            if trend_flipped(
                df, trade["direction"],
                ema_trend_period=entry_cfg.get("ema_trend", 200),
                bar_idx=-2,
                chop_band_atr=entry_cfg.get("chop_band_atr", 0.5),
            ):
                tick = mt5.symbol_info_tick(symbol)
                close_price = (tick.bid if trade["direction"] == "BUY" else tick.ask) if tick else None
                if close_order(ticket, symbol, trade["direction"], trade["lot_size"]):
                    logger.info(f"[{symbol}] TREND-FLIP EXIT: closing {trade['direction']}")
                    self._record_manual_close(trade, close_price, "trend_flip")

        if synced:
            logger.info(f"Synced {synced} closed position(s) from MT5")

    # ── Per-market entry path ────────────────────────────────────────────────
    def _process_market(self, market_key: str, cfg: dict, balance: float):
        candidates = cfg.get("symbol_candidates") or [cfg.get("symbol", market_key)]
        symbol = resolve_symbol(candidates)
        if not symbol:
            logger.warning(
                f"[{market_key}] No matching symbol on broker (tried {candidates}) — skipping."
            )
            return

        # Single trade per symbol — skip if a position is already open on this symbol.
        if get_open_positions(symbol):
            return

        entry_cfg = cfg["entry"]

        # Cooldown: time since last exit must exceed cooldown_bars × 15 min.
        cooldown_bars = entry_cfg.get("cooldown_bars", 0)
        if cooldown_bars > 0:
            last = TradeRepo.get_last_closed_trade(symbol)
            if last and last.get("exit_time"):
                exit_time = last["exit_time"]
                if isinstance(exit_time, str):
                    exit_time = datetime.fromisoformat(exit_time)
                cooldown_until = exit_time + timedelta(minutes=15 * cooldown_bars)
                if datetime.now(timezone.utc) < cooldown_until:
                    return

        df = fetch_candles(symbol, mt5.TIMEFRAME_M15, count=300)
        if df.empty or len(df) < 210:
            logger.info(f"[{symbol}] insufficient bars ({len(df)})")
            return

        setup = find_entry(df, entry_cfg, bar_idx=-2)
        if setup is None:
            return

        # max_sl_usd cap — reject if A's loss would exceed configured threshold.
        lot = cfg["dual_trade"]["trade_a_lot"]
        sym_info = get_symbol_info(symbol)
        contract = sym_info.trade_contract_size if sym_info else 100_000
        max_sl_usd = entry_cfg.get("max_sl_usd", 0)
        if max_sl_usd > 0:
            sl_dist = abs(setup.entry_price - setup.sl)
            potential_loss = sl_dist * lot * contract
            if potential_loss > max_sl_usd:
                logger.info(
                    f"[{symbol}] SL too wide (${potential_loss:.2f} > cap ${max_sl_usd}) — skipping"
                )
                return

        # Risk-manager veto (daily loss cap, max open trades, etc.)
        can_trade, reason = self.risk.can_trade(symbol, balance)
        if not can_trade:
            logger.warning(f"[{symbol}] Risk blocked: {reason}")
            return

        logger.info(
            f"[{symbol}] SIGNAL {setup.direction} | pattern={setup.pattern} | "
            f"entry≈{setup.entry_price:.5f} sl={setup.sl:.5f} tp={setup.tp:.5f} | "
            f"preset={cfg.get('strategy_preset', '?')}"
        )

        order = place_order(symbol, setup.direction, lot, setup.sl, setup.tp,
                            comment=f"trend_{setup.pattern}")
        if not order:
            logger.error(f"[{symbol}] Order placement failed")
            return

        TradeRepo.open_trade(
            symbol=symbol, direction=setup.direction,
            entry_price=order["price"], sl=setup.sl, tp=setup.tp,
            lot_size=lot, ticket=order["ticket"],
            strategy="trend_follower", timeframe="M15",
            rsi=0.0, atr=setup.atr, ema_trend=setup.ema_trend,
        )

    # ── Close persistence ────────────────────────────────────────────────────
    def _record_mt5_close(self, trade: dict):
        history     = mt5.history_deals_get(position=trade["ticket"])
        exit_price  = None
        exit_reason = "UNKNOWN"
        if history:
            for deal in history:
                if deal.entry == 1:
                    exit_price  = deal.price
                    exit_reason = "TP" if deal.profit > 0 else ("SL" if deal.profit < 0 else "MANUAL")
                    break
        if exit_price is None:
            logger.warning(
                f"[{trade['symbol']}] Exit deal not found for ticket {trade['ticket']} "
                f"— recording at entry price"
            )
            exit_price  = trade["entry_price"]
            exit_reason = "UNKNOWN"
        self._write_close(trade, exit_price, exit_reason)

    def _record_manual_close(self, trade: dict, close_price, reason: str):
        if close_price is None:
            close_price = trade["entry_price"]
        self._write_close(trade, close_price, reason)

    def _write_close(self, trade: dict, exit_price: float, exit_reason: str):
        entry = trade["entry_price"]
        qty   = trade["lot_size"]
        pnl   = (exit_price - entry) * qty if trade["direction"] == "BUY" \
                else (entry - exit_price) * qty
        cost  = entry * qty
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
            logger.info(f"Balance after close: ${new_balance:.2f}")