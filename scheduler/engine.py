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
                pos = next(p for p in mt5_positions if p["ticket"] == ticket)

                # Weak-market smart exit (profit/BE when momentum fades)
                should_exit, reason = self._weak_market_exit(trade, pos)
                if should_exit:
                    from broker.mt5_connector import close_order
                    tick = mt5.symbol_info_tick(trade["symbol"])
                    close_price = (
                        tick.bid if trade["direction"] == "BUY" else tick.ask
                    ) if tick else None
                    if close_order(ticket, trade["symbol"], trade["direction"], trade["lot_size"]):
                        logger.info(f"[{trade['symbol']}] WEAK-MARKET EXIT — {reason}")
                        self._record_manual_close(trade, close_price, "Weak Market Exit")
                        continue

                # Profit-target monitor: close if live P/L >= cfg['exit_at_profit_usd']
                if self._profit_target_hit(trade, pos):
                    from broker.mt5_connector import close_order
                    tick = mt5.symbol_info_tick(trade["symbol"])
                    close_price = (
                        tick.bid if trade["direction"] == "BUY" else tick.ask
                    ) if tick else None
                    if close_order(ticket, trade["symbol"], trade["direction"], trade["lot_size"]):
                        logger.info(
                            f"[{trade['symbol']}] PROFIT-TARGET EXIT at ${pos['profit']:.2f}"
                        )
                        self._record_manual_close(trade, close_price, "Profit Target")
                        continue

                # Signal-reversal / invalidation early exit
                if self._should_early_exit(trade):
                    from broker.mt5_connector import close_order
                    tick = mt5.symbol_info_tick(trade["symbol"])
                    close_price = (
                        tick.bid if trade["direction"] == "BUY" else tick.ask
                    ) if tick else None

                    if close_order(ticket, trade["symbol"], trade["direction"], trade["lot_size"]):
                        logger.info(f"[{trade['symbol']}] EARLY EXIT: Signal Invalidated or Reversed")
                        self._record_manual_close(trade, close_price, "Early Exit")
                        continue

                self._handle_trailing_stop(trade, pos)

        if synced:
            logger.info(f"Synced {synced} closed position(s) from MT5")

    def _weak_market_exit(self, trade: dict, pos: dict) -> tuple:
        """
        Smart exit when market momentum fades (per user spec):
          - Current candle body weak (below threshold) = market not worth staying in
          - If in profit  -> close immediately (lock what we have)
          - If at BE      -> close (walk away flat)
          - If small loss -> DO NOT CLOSE. Wait for recovery to BE/profit.
          - If big loss   -> let broker SL handle it (no action here)

        Active only when strategy == "scalper" and cfg.weak_exit_enabled is True.
        Per-market configurable:
          weak_exit_enabled       (bool, default False)
          weak_body_threshold     (float, default 0.5)   — body_pct below this = weak
          be_tolerance_usd        ($,    default 0.50)   — within +/- this = BE
          small_loss_limit_usd    ($,    default 5.00)   — losses up to this = "small"

        Returns (should_close: bool, reason: str).
        """
        symbol = trade["symbol"]
        cfg    = MARKETS.get(symbol)
        if not cfg or cfg.get("strategy") != "scalper":
            return False, ""

        filters = cfg.get("filters", {})
        if not cfg.get("weak_exit_enabled"):
            return False, ""

        weak_threshold = cfg.get("weak_body_threshold", 0.5)
        be_tol         = cfg.get("be_tolerance_usd",   0.50)
        small_loss     = cfg.get("small_loss_limit_usd", 5.00)

        trend_filter_enabled = filters.get("trend_filter_enabled", False)
        trend_adx_min        = filters.get("trend_adx_min", 20)

        # Fetch latest candles (need 210+ for EMA200 if trend filter is on)
        bars_needed = 210 if trend_filter_enabled else 20
        df = fetch_candles(symbol, cfg["timeframe"], count=bars_needed)
        if df.empty or len(df) < 3:
            return False, ""

        idx = -2  # last completed candle
        o, h, l, c = (df["Open"].iloc[idx], df["High"].iloc[idx],
                      df["Low"].iloc[idx], df["Close"].iloc[idx])
        rng = h - l
        if rng <= 0:
            return False, ""
        body_pct = abs(c - o) / rng

        # ── Trend-aware override (your spec: ride the trend, escape only when it dies) ──
        if trend_filter_enabled and len(df) >= 205:
            import math as _math
            from strategies.indicators import calc_ema, calc_adx
            ema50  = calc_ema(df, 50).iloc[idx]
            ema200 = calc_ema(df, 200).iloc[idx]
            adx_v  = calc_adx(df, 14).iloc[idx]

            if not (_math.isnan(ema50) or _math.isnan(ema200) or _math.isnan(adx_v)):
                trend_up   = c > ema50 and ema50 > ema200 and adx_v >= trend_adx_min
                trend_down = c < ema50 and ema50 < ema200 and adx_v >= trend_adx_min
                trade_dir  = trade["direction"]

                # Trend still with us -> HOLD regardless of candle strength
                if (trade_dir == "BUY"  and trend_up) or \
                   (trade_dir == "SELL" and trend_down):
                    return False, ""

                # Trend flipped against us -> CLOSE immediately
                if (trade_dir == "BUY"  and trend_down) or \
                   (trade_dir == "SELL" and trend_up):
                    return True, f"Trend reversed (ADX:{adx_v:.1f})"

        # ── Standard momentum-fade logic (trend weak or filter off) ──
        # Market still showing momentum? Let the trade run.
        if body_pct >= weak_threshold:
            return False, ""

        # Market weakened — apply exit rules based on current P/L
        profit = pos.get("profit", 0)

        if profit >= be_tol:
            return True, f"Weak market + in profit (body {body_pct:.2f}, P/L ${profit:+.2f})"
        if profit >= -be_tol:
            return True, f"Weak market + at breakeven (body {body_pct:.2f}, P/L ${profit:+.2f})"
        if profit >= -small_loss:
            # Small loss — hold and wait for recovery.
            return False, ""
        # Big loss — let SL do its job
        return False, ""


    def _profit_target_hit(self, trade: dict, pos: dict) -> bool:
        """
        Return True if the live floating profit (from broker) on this position
        has reached the market's configured exit_at_profit_usd threshold.

        Configure per market in config/markets.py:
            "exit_at_profit_usd": 2.00   # close when P/L reaches +$2 (or more)

        If the field is absent or 0, the monitor is disabled for that market.
        """
        symbol = trade["symbol"]
        cfg    = MARKETS.get(symbol)
        if not cfg:
            return False
        target = cfg.get("exit_at_profit_usd")
        if not target or target <= 0:
            return False
        return pos.get("profit", 0) >= target

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
        Break-Even management: moves SL to entry once profit reaches 0.5x ATR.
        Triggers early to protect profit — once activated, worst case is break-even (0 loss).
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

            # Move SL to entry once profit >= 0.5x ATR (only if SL still below entry)
            if profit_dist >= atr_entry * 0.5 and current_sl < entry_price:
                update_stops(trade["ticket"], symbol, entry_price, current_tp)
                logger.info(f"[{symbol}] BREAK-EVEN: SL moved to entry {entry_price:.5f}")

        else:  # SELL
            current_price = tick.ask
            profit_dist   = entry_price - current_price

            # Move SL to entry once profit >= 0.5x ATR (only if SL still above entry)
            if profit_dist >= atr_entry * 0.5 and current_sl > entry_price:
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

    def _process_market(self, market_key: str, cfg: dict, balance: float):
        # Resolve the actual MT5 symbol from candidates (e.g. BTCUSD vs BTCUSDm).
        from broker.mt5_connector import resolve_symbol
        candidates = cfg.get("symbol_candidates") or cfg.get("symbol") or market_key
        symbol = resolve_symbol(candidates)
        if not symbol:
            logger.warning(
                f"[{market_key}] No matching symbol on this account "
                f"(tried: {candidates}) — skipping."
            )
            return

        # Reuse cfg with resolved symbol (so downstream code doesn't have to know about candidates)
        cfg = {**cfg, "symbol": symbol}
        logger.info(f"── Analysing {symbol} [{cfg['tf_name']}] ──")

        # ── New structure-trader strategy — dual orders + structural monitor + cooldown
        if cfg.get("strategy") == "structure_trader":
            self._process_structure_trader(symbol, cfg, balance)
            return

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

        # ─── Balance-Based Market Rules ───────────────────
        # XAGUSD only: skip if balance is below $500 (silver lots are expensive).
        # XAUUSD on Exness: 0.01 lot is fine on $200+ accounts.
        if symbol == "XAGUSD" and balance < 500:
            logger.warning(
                f"[{symbol}] Skipped — balance ${balance:.2f} < $500 minimum for this market"
            )
            return

        # ─── Position Sizing ──────────────────────────────
        # Fixed min_lot per market. Increase min_lot in markets.py to scale up.
        sym_info    = get_symbol_info(symbol)
        sym_min_lot = cfg.get("min_lot")
        if sym_min_lot is None:
            sym_min_lot = sym_info.volume_min if sym_info else settings.MIN_LOT_SIZE

        # ─── Order Count: Boom 1000 scales with balance ───
        # All other markets: 1 order (fixed).
        # Boom 1000 Index: scale up order count as account grows.
        if symbol == "Boom 1000 Index":
            if balance >= 500:
                num_orders = 10
            elif balance >= 200:
                num_orders = 5
            elif balance >= 100:
                num_orders = 3
            else:
                num_orders = 1
        else:
            num_orders = 1

        tp = signal.tp1

        # ─── Fixed-Dollar Profit Target Override ──────────
        # If cfg defines profit_target_usd, compute TP as the exact price where
        # profit = target. This overrides the scalper's rr_ratio-based TP.
        profit_target = cfg.get("filters", {}).get("profit_target_usd")
        if profit_target and sym_info:
            contract = sym_info.trade_contract_size
            if contract and sym_min_lot:
                price_move = profit_target / (sym_min_lot * contract)
                entry_price = signal.close  # close of trigger candle (entry estimate)
                tp = entry_price + price_move if signal.direction == "BUY" \
                     else entry_price - price_move
                logger.info(
                    f"[{symbol}] TP override: ${profit_target} target -> "
                    f"price move ${price_move:.3f} -> TP {tp:.5f}"
                )

        logger.info(
            f"[{symbol}] Placing {num_orders} order(s) | "
            f"Lot: {sym_min_lot} each | SL: {signal.sl:.5f} | TP: {tp:.5f}"
        )

        for i in range(1, num_orders + 1):
            order = place_order(
                symbol    = symbol,
                direction = signal.direction,
                lot_size  = sym_min_lot,
                sl        = signal.sl,
                tp        = tp,
                comment   = f"UB_{cfg['strategy']}_{i}" if num_orders > 1 else f"UB_{cfg['strategy']}",
            )

            if not order:
                logger.error(f"[{symbol}] Order placement FAILED (order {i}/{num_orders})")
                continue

            TradeRepo.open_trade(
                symbol      = symbol,
                direction   = signal.direction,
                entry_price = order["price"],
                sl          = signal.sl,
                tp          = tp,
                lot_size    = sym_min_lot,
                ticket      = order["ticket"],
                strategy    = cfg["strategy"],
                timeframe   = cfg["tf_name"],
                rsi         = signal.rsi,
                atr         = signal.atr,
                ema_trend   = signal.ema_trend,
            )

            logger.info(
                f"Trade executed ({i}/{num_orders}) | {signal.direction} {symbol} | "
                f"Lot: {sym_min_lot} | TP: {tp:.5f} | Ticket: {order['ticket']}"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # STRUCTURE TRADER (Phase 5)
    # ═══════════════════════════════════════════════════════════════════════

    def _process_structure_trader(self, symbol: str, cfg: dict, balance: float):
        """
        Main path for strategy='structure_trader'.

        Per cycle:
          1. For any open struct_A trades: run M15 structure invalidation check.
          2. For any open struct_B trades: run $2 profit target check.
          3. If no open positions for this symbol AND cooldown cleared:
             → run structure_trader.analyze, place dual orders on setup.
        """
        from strategies.structure_trader import analyze, cooldown_cleared
        from broker.mt5_connector import close_order, get_symbol_info, place_order

        # Step 1 & 2: manage open structure trades
        open_for_sym = [p for p in get_open_positions(symbol) or []]
        for pos in open_for_sym:
            self._manage_open_structure_trade(pos, symbol, cfg)

        # Refresh open positions after potential closures above
        open_after = get_open_positions(symbol) or []
        if open_after:
            logger.info(f"[{symbol}] {len(open_after)} open structure position(s) — not looking for new entries.")
            return

        # Step 3: look for new signal
        decision = analyze(symbol, cfg)
        logger.info(f"[{symbol}] BIAS={decision.bias} | {decision.reason}")

        if decision.setup is None:
            return

        # Structural cooldown
        last_exit = StateRepo.get(f"struct_last_exit_{symbol}")
        if not cooldown_cleared(last_exit, decision.latest_swing_time):
            logger.info(f"[{symbol}] Cooldown active — waiting for new confirmed M15 swing since last exit.")
            return

        # Risk / balance checks
        can_trade, block_reason = self.risk.can_trade(symbol, balance)
        if not can_trade:
            logger.warning(f"[{symbol}] Trade blocked by risk — {block_reason}")
            return

        self._place_dual_orders(symbol, cfg, decision.setup, balance)

    def _manage_open_structure_trade(self, pos: dict, symbol: str, cfg: dict):
        """Route a single open position through the right monitor (A or B)."""
        from broker.mt5_connector import close_order
        import MetaTrader5 as mt5

        # Find the DB trade record to know role + invalidation
        db_open = TradeRepo.get_open_trades()
        trade = next((t for t in db_open if t.get("ticket") == pos["ticket"]), None)
        if trade is None:
            return  # not tracked — could be manual trade, skip

        role = trade.get("trade_role", "A")

        # ── TRADE B — close on $2 profit target ──
        if role == "B":
            target = trade.get("tp_b_profit_usd", 0)
            if target > 0 and pos.get("profit", 0) >= target:
                tick = mt5.symbol_info_tick(symbol)
                close_price = (tick.bid if pos["direction"] == "BUY" else tick.ask) if tick else None
                if close_order(pos["ticket"], symbol, pos["direction"], pos["lot_size"]):
                    logger.info(f"[{symbol}] struct_B TARGET HIT ${pos['profit']:.2f} >= ${target}")
                    self._record_manual_close(trade, close_price, "Trade B target")
                    StateRepo.set(f"struct_last_exit_{symbol}", datetime.now(timezone.utc).isoformat())
                    # ★ When B hits target: move A's SL to breakeven so A can no longer lose.
                    self._move_a_to_breakeven(symbol, trade["direction"], trade["entry_price"])
            return

        # ── TRADE A — M15 structure-break monitor ──
        inv = trade.get("invalidation_price")
        if not inv:
            return
        df_m15 = fetch_candles(symbol, mt5.TIMEFRAME_M15, count=10)
        if df_m15.empty or len(df_m15) < 2:
            return
        last_close = float(df_m15["Close"].iloc[-2])   # last CLOSED bar
        broke = False
        if pos["direction"] == "BUY"  and last_close < inv: broke = True
        if pos["direction"] == "SELL" and last_close > inv: broke = True
        if broke:
            tick = mt5.symbol_info_tick(symbol)
            close_price = (tick.bid if pos["direction"] == "BUY" else tick.ask) if tick else None
            if close_order(pos["ticket"], symbol, pos["direction"], pos["lot_size"]):
                logger.info(
                    f"[{symbol}] struct_A STRUCTURE INVALIDATED — "
                    f"last M15 close ${last_close:.2f} beyond invalidation ${inv:.2f}"
                )
                self._record_manual_close(trade, close_price, "M15 structure invalidated")
                StateRepo.set(f"struct_last_exit_{symbol}", datetime.now(timezone.utc).isoformat())

    def _move_a_to_breakeven(self, symbol: str, direction: str, entry_price: float):
        """
        Find the matching open struct_A position for this symbol/direction and
        move its SL to entry (plus a tiny buffer to lock a cent of profit).
        Called right after struct_B hits its target.
        """
        from broker.mt5_connector import update_stops
        buffer = 0.10   # $0.10 buffer in direction of trade
        new_sl = entry_price + buffer if direction == "BUY" else entry_price - buffer

        for p in get_open_positions(symbol) or []:
            if p.get("comment", "").startswith("struct_A") and p["direction"] == direction:
                if update_stops(p["ticket"], symbol, new_sl, p["tp"]):
                    logger.info(
                        f"[{symbol}] struct_A SL moved to BE (entry {entry_price:.2f} → SL {new_sl:.2f}) "
                        f"because struct_B just hit target"
                    )
                break

    def _place_dual_orders(self, symbol: str, cfg: dict, setup, balance: float = 0.0):
        """
        Place trade A (main) + trade B (scalp).
        Trade A: structural SL (setup.sl), TP at min_rr target.
        Trade B: TIGHTER SL capped by trade_b_max_loss_usd, TP at +$tp_b_profit_usd.

        Trade B is skipped if account balance is below `min_balance_for_b`
        (capital protection on small accounts).
        """
        from broker.mt5_connector import place_order, get_symbol_info

        dual = cfg.get("dual_trade", {})
        lot_a       = dual.get("trade_a_lot", 0.01)
        lot_b       = dual.get("trade_b_lot", 0.01)
        tp_b_usd    = dual.get("trade_b_profit_usd", 2.0)
        b_max_loss  = dual.get("trade_b_max_loss_usd", 5.0)
        min_bal_b   = dual.get("min_balance_for_b", 0.0)
        skip_b_low_balance = balance > 0 and min_bal_b > 0 and balance < min_bal_b
        if skip_b_low_balance:
            logger.info(
                f"[{symbol}] Trade B skipped — balance ${balance:.2f} < min ${min_bal_b:.2f} "
                f"(small-account capital protection)"
            )

        sym_info = get_symbol_info(symbol)
        if not sym_info:
            logger.error(f"[{symbol}] No symbol info — cannot size orders")
            return

        contract = sym_info.trade_contract_size

        logger.info(
            f"[{symbol}] STRUCTURE SETUP ({setup.scenario}) | {setup.direction} | "
            f"signal entry≈${setup.entry_price:.2f} | "
            f"A: SL ${setup.sl:.2f} TP ${setup.tp_a:.2f}"
        )

        # ── Place Trade A first — at structural SL/TP ──
        order_a = place_order(symbol, setup.direction, lot_a, setup.sl, setup.tp_a, comment="struct_A")
        if not order_a:
            return  # A failed → don't bother with B

        a_fill_price = order_a["price"]
        TradeRepo.open_trade_struct(
            symbol=symbol, direction=setup.direction,
            entry_price=a_fill_price, sl=setup.sl, tp=setup.tp_a, lot_size=lot_a,
            ticket=order_a["ticket"], strategy="structure_trader",
            timeframe=cfg.get("tf_name", "M15"),
            trade_role="A", invalidation_price=setup.invalidation_price,
            tp_b_profit_usd=0.0, scenario=setup.scenario,
        )

        # ── Trade B sized off A's ACTUAL fill price ──
        # (signal price can be stale by the time orders fill; using A's fill
        # ensures B's SL/TP are valid relative to the real entry.)
        if tp_b_usd > 0 and lot_b > 0 and contract > 0 and not skip_b_low_balance:
            # Recompute B's SL distance from the structural SL relative to actual fill
            struct_sl_dist = abs(a_fill_price - setup.sl)
            b_max_dist = b_max_loss / (lot_b * contract) if b_max_loss > 0 else struct_sl_dist
            b_sl_dist = min(struct_sl_dist, b_max_dist)
            b_sl = (a_fill_price - b_sl_dist) if setup.direction == "BUY" else (a_fill_price + b_sl_dist)

            tp_b_dist = tp_b_usd / (lot_b * contract)
            tp_b_price = (a_fill_price + tp_b_dist) if setup.direction == "BUY" \
                         else (a_fill_price - tp_b_dist)

            logger.info(
                f"[{symbol}] B sized off A fill ${a_fill_price:.2f} | "
                f"B: SL ${b_sl:.2f} (cap ${b_max_loss}) TP ${tp_b_price:.2f} (+${tp_b_usd})"
            )

            order_b = place_order(symbol, setup.direction, lot_b, b_sl, tp_b_price, comment="struct_B")
            if order_b:
                TradeRepo.open_trade_struct(
                    symbol=symbol, direction=setup.direction,
                    entry_price=order_b["price"], sl=b_sl, tp=tp_b_price, lot_size=lot_b,
                    ticket=order_b["ticket"], strategy="structure_trader",
                    timeframe=cfg.get("tf_name", "M15"),
                    trade_role="B", invalidation_price=setup.invalidation_price,
                    tp_b_profit_usd=tp_b_usd, scenario=setup.scenario,
                )
