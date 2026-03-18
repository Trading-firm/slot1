"""
scheduler/engine.py
────────────────────
The main trading engine.
Orchestrates the full cycle:
  1. Fetch candle data
  2. Run strategy analysis
  3. Check risk rules
  4. Execute trades
  5. Monitor open trades for SL/TP
  6. Log everything to MongoDB
"""

from dataclasses import asdict, is_dataclass
from broker.connector import ForexBroker
from strategies.ema_rsi import EMARSIStrategy
from strategies.bollinger_breakout import BollingerBreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.macd_cross import MACDCrossStrategy
from strategies.stochastic_oscillator import StochasticStrategy
from strategies.atr_breakout import ATRBreakoutStrategy
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.cci_trend import CCITrendStrategy
from strategies.parabolic_sar import ParabolicSARStrategy
from strategies.rsi_stoch import RSIStochStrategy
from strategies.support_resistance import SupportResistanceStrategy
from strategies.candlestick_pattern import CandlestickPatternStrategy
from strategies.fvg_strategy import FVGStrategy
from utils.risk_manager import RiskManager
from database.models import init_db
from database.repository import (
    TradeRepository, SignalRepository, DailySummaryRepository, BotStateRepository
)
from config.settings import settings
from utils.logger import logger
from notifications.telegram_bot import send_telegram_message
import pandas as pd
from datetime import datetime
import ta


class TradingEngine:
    """Core engine that runs on every scheduled tick."""

    def __init__(self):
        logger.info("Initialising Trading Engine...")
        init_db()
        self.broker   = ForexBroker()
        
        # Initialize all strategies
        self.strategies_map = {
            "ema_rsi": EMARSIStrategy(),
            "bollinger_breakout": BollingerBreakoutStrategy(),
            "mean_reversion": MeanReversionStrategy(),
            "macd_cross": MACDCrossStrategy(),
            "stochastic": StochasticStrategy(),
            "atr_breakout": ATRBreakoutStrategy(),
            "sma_crossover": SMACrossoverStrategy(),
            "cci_trend": CCITrendStrategy(),
            "parabolic_sar": ParabolicSARStrategy(),
            "rsi_stoch": RSIStochStrategy(),
            "support_resistance": SupportResistanceStrategy(),
            "candlestick_pattern": CandlestickPatternStrategy(),
            "fvg": FVGStrategy()
        }
        
        self.risk     = RiskManager()
        self.pairs    = settings.TRADING_PAIRS
        self.tf       = settings.TIMEFRAME
        self.mode     = settings.TRADE_MODE
        logger.info(
            f"Engine ready | Mode: {self.mode.upper()} | "
            f"Pairs: {self.pairs} | Timeframe: {self.tf}"
        )

    # ─── Main Cycle ───────────────────────────────────────
    def run_cycle(self):
        """Full cycle: monitor open trades → scan signals → execute."""
        logger.info("=" * 60)
        logger.info("NEW CYCLE STARTING")
        logger.info("=" * 60)
        
        # Update heartbeat
        BotStateRepository.set("heartbeat", datetime.utcnow().isoformat())

        try:
            balance = self.broker.get_balance()
            BotStateRepository.set("last_balance", f"{float(balance)}")
            logger.info(f"Account balance: ${balance:.2f}")
            self.risk.print_risk_summary(balance)

            # Step 1 — Monitor and close open trades if SL/TP hit
            self._monitor_open_trades()

            # Step 2 — Scan all pairs for new signals
            self._scan_for_signals(balance)

            # Step 3 — Update daily summary
            DailySummaryRepository.upsert_summary()

        except Exception as e:
            logger.error(f"Critical error in run cycle: {e}", exc_info=True)

        logger.info("CYCLE COMPLETE")
        logger.info("=" * 60)

    # ─── Monitor Open Trades ──────────────────────────────
    def _monitor_open_trades(self):
        """
        Check all open trades:
        1. Verify if they are still open on Broker (MT5).
           - If closed on MT5 (SL/TP), update DB immediately.
        2. If still open, check if Strategy signals exit.
        """
        open_trades = TradeRepository.get_open_trades()

        if not open_trades:
            logger.info("No open trades to monitor.")
            return

        logger.info(f"Monitoring {len(open_trades)} open trade(s)...")

        # ─── 1. Sync with Broker (Detect SL/TP hits) ───
        if hasattr(self.broker, "get_open_positions"):
            try:
                broker_positions = self.broker.get_open_positions()
                # Create a set of open tickets for fast lookup (as integers)
                open_tickets = {int(p["ticket"]) for p in broker_positions if str(p["ticket"]).isdigit()}
                
                trades_still_open = []
                
                for trade in open_trades:
                    ticket_str = trade.get("broker_order_id")
                    
                    # Convert DB ticket to int for comparison
                    try:
                        ticket = int(ticket_str) if ticket_str and str(ticket_str).isdigit() else None
                    except (ValueError, TypeError):
                        ticket = None

                    # If trade has a valid ticket but is NOT in broker positions -> It Closed!
                    if ticket and ticket not in open_tickets:
                        logger.info(f"Trade {ticket} ({trade['pair']}) missing from broker positions. Checking history...")
                        
                        # Get closure details from history
                        if hasattr(self.broker, "get_closed_trade_info"):
                            info = self.broker.get_closed_trade_info(ticket)
                            if info:
                                TradeRepository.close_trade(
                                    trade_id=trade["_id"],
                                    exit_price=info["exit_price"],
                                    exit_reason=f"Broker: {info['reason']}",
                                    pnl=info["pnl"],
                                    pnl_pct=0.0 # TODO: Calculate pct if needed, or update repository to calc it
                                )
                                logger.info(f"Synced closed trade {ticket}: PnL=${info['pnl']:.2f}, Reason={info['reason']}")
                                continue # Skip to next trade, don't process strategy exit
                            else:
                                logger.warning(f"Could not find history for closed trade {ticket}")
                    
                    # If we are here, trade is either still open OR has no ticket (paper/error)
                    trades_still_open.append(trade)
                
                # Only process strategy checks for trades that are actually open
                open_trades = trades_still_open

            except Exception as e:
                logger.error(f"Error syncing with broker positions: {e}")

        # ─── 2. Strategy Exit Checks ───
        # Group trades by (pair, timeframe) to optimize data fetching
        grouped_trades = {}
        for trade in open_trades:
            # Default to self.tf if timeframe missing (legacy support)
            tf = trade.get("timeframe", self.tf)
            key = (trade["pair"], tf)
            if key not in grouped_trades:
                grouped_trades[key] = []
            grouped_trades[key].append(trade)

        # Process each group
        for (pair, tf), trades in grouped_trades.items():
            try:
                # Fetch live ticker (fast, for SL/TP check)
                ticker = self.broker.fetch_ticker(pair)
                
                # Fetch historical data (slower, for Strategy Exit check)
                # We need enough candles for indicators (e.g., EMA200)
                df = self.broker.fetch_ohlcv(pair, timeframe=tf, limit=300)
                
                # Iterate trades in this group
                for trade in trades:
                    self._check_and_close_trade(trade, ticker, df)

            except Exception as e:
                logger.error(f"Error monitoring trades for {pair} ({tf}): {e}")

    def _check_and_close_trade(self, trade: dict, ticker: dict, df: pd.DataFrame):
        """Check single trade for exit conditions (Risk or Strategy)."""
        should_close = False
        reason = ""

        try:
            # A. Check Hard SL/TP (Risk Manager)
            should_close, reason, exit_price = self.risk.check_exit(trade, ticker)
            
            # B. Check Strategy Early Exit (if not already closing due to SL/TP)
            if not should_close and not df.empty:
                strat_name = trade.get("strategy")
                strategy   = self.strategies_map.get(strat_name)
                
                # Only if strategy supports check_exit
                if strategy and hasattr(strategy, "check_exit"):
                    try:
                        # Calculate indicators on a copy to avoid pollution/conflicts
                        strat_df = strategy.calculate_indicators(df.copy())
                        
                        if not strat_df.empty:
                            curr = strat_df.iloc[-1]
                            should_exit, exit_reason = strategy.check_exit(curr, trade)
                            
                            if should_exit:
                                # IMMEDIATE EXIT on Strategy Invalidation
                                # The user requested: "if anything goes wrong in the initial decision it should close the trade immediately."
                                # We remove the pending confirmation (delay) to act instantly on reversal signals.
                                should_close = True
                                reason = f"Strategy Invalidation: {exit_reason}"
                                logger.warning(f"🚨 IMMEDIATE EXIT TRIGGERED: {reason} for trade {trade.get('_id')}")
                                
                                # Reset any pending flags just in case
                                TradeRepository.reset_exit_pending(trade["_id"])
                            else:
                                TradeRepository.reset_exit_pending(trade["_id"])
                                
                    except Exception as s_err:
                        logger.warning(f"Strategy check_exit failed for {strat_name}: {s_err}")

            # Execute Close or Log Status
            if should_close:
                TradeRepository.reset_exit_pending(trade["_id"])
                self._execute_close(trade, exit_price if exit_price is not None else ticker.get("last"), reason)
            else:
                self._log_open_trade_status(trade, float(ticker.get("last")) if ticker.get("last") is not None else 0.0)
                
        except Exception as e:
            logger.error(f"Error checking trade {trade.get('_id')}: {e}")

    def _execute_close(self, trade: dict, exit_price: float, reason: str):
        """Execute the trade closure and update DB/Notifications."""
        try:
            pnl, pnl_pct = self.risk.calculate_pnl(trade, exit_price)

            # Close in broker
            broker_order_id = trade.get("broker_order_id")
            closed_ok = self.broker.close_order(order_id=broker_order_id, exit_price=exit_price) if broker_order_id is not None else False

            if not closed_ok:
                logger.warning(
                    f"Close skipped for DB sync: broker close failed or missing ticket | "
                    f"trade_id={trade.get('_id')} | broker_order_id={broker_order_id}"
                )
                return

            # Update database
            TradeRepository.close_trade(
                trade_id   = trade["_id"],
                exit_price = exit_price,
                exit_reason= reason,
                pnl        = pnl,
                pnl_pct    = pnl_pct,
            )

            emoji = "✅" if pnl > 0 else "❌"
            log_msg = (
                f"{emoji} Trade closed | {trade['pair']} {trade['direction']} | "
                f"Reason: {reason} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)"
            )
            logger.info(log_msg)

            # Send Notification
            try:
                msg = (
                    f"{emoji} *Trade Closed*\n"
                    f"Pair: {trade['pair']}\n"
                    f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%)\n"
                    f"Reason: {reason}"
                )
                send_telegram_message(msg)
            except Exception as e:
                logger.error(f"Failed to send close notification: {e}")

        except Exception as e:
            logger.error(f"Critical error executing close for {trade.get('_id')}: {e}")

    def _log_open_trade_status(self, trade: dict, current_price: float):
        """Log the status of an open trade."""
        floating_pnl, _ = self.risk.calculate_pnl(trade, current_price)
        logger.info(
            f"📊 Open: {trade['pair']} {trade['direction']} | "
            f"Entry: {trade['entry_price']:.5f} | "
            f"Current: {current_price:.5f} | "
            f"Floating PnL: ${floating_pnl:.2f}"
        )

    # ─── Helper: Save Signal ──────────────────────────────
    def _save_signal_to_db(self, signal, strat_name: str, timeframe: str, acted_on: bool, trade_id: str = None, skip_reason: str = None, risk_metrics: dict = None):
        """Helper to save signal to database with metadata."""
        try:
            # Prepare Metadata (Strategy Indicators + Risk Metrics)
            metadata = {}
            
            # 1. Add Risk Metrics
            if risk_metrics:
                metadata.update(risk_metrics)

            # 2. Add Strategy Signal Details (Indicators, SL/TP)
            try:
                if is_dataclass(signal):
                    sig_dict = asdict(signal)
                else:
                    sig_dict = signal.__dict__
                
                exclude = {
                    "pair", "signal", "close", "reason", 
                    "ema_fast", "ema_slow", "rsi", "atr", "bb_upper", "bb_lower"
                }
                for k, v in sig_dict.items():
                    if k not in exclude and not k.startswith("_"):
                        metadata[k] = v
            except Exception as meta_err:
                logger.warning(f"Failed to serialize signal to metadata: {meta_err}")

            # Build args dynamically based on signal type
            sig_kwargs = {
                "pair":           signal.pair,
                "signal_type":    signal.signal,
                "timeframe":      timeframe,
                "close_price":    signal.close,
                "acted_on":       acted_on,
                "reason_skipped": skip_reason,
                "strategy":       strat_name,
                "atr":            getattr(signal, "atr", None),
                "rsi":            getattr(signal, "rsi", None),
                "metadata":       metadata,
                "trade_id":       trade_id,
            }
            
            # Add extra attributes if they exist
            for attr in ["ema_fast", "ema_slow", "bb_upper", "bb_lower"]:
                if hasattr(signal, attr):
                    sig_kwargs[attr] = getattr(signal, attr)

            SignalRepository.create_signal(**sig_kwargs)
        except Exception as e:
            logger.error(f"Failed to save signal to DB: {e}")

    # ─── Scan For Signals ─────────────────────────────────
    def _scan_for_signals(self, balance: float):
        """Scan all configured pairs for entry signals."""
        logger.info(f"Scanning {len(self.pairs)} pair(s) for signals...")

        for pair in self.pairs:
            try:
                self._process_pair(pair, balance)
            except Exception as e:
                logger.error(f"Error processing {pair}: {e}")

    def _process_pair(self, pair: str, balance: float):
        """Full signal → risk → execute flow for one pair."""
        logger.info(f"Analysing {pair}...")

        # Get strategy configuration for this pair
        pair_config = settings.STRATEGY_CONFIG.get(pair, settings.STRATEGY_CONFIG.get("default", []))
        
        # Handle new dictionary format for advanced configuration
        required_strategies = []
        min_confluence_override = None
        
        if isinstance(pair_config, dict) and "strategies" in pair_config:
            configs = pair_config["strategies"]
            required_strategies = pair_config.get("required_confluence", [])
            min_confluence_override = pair_config.get("min_confluence")
        else:
            configs = pair_config

        if not configs:
            logger.warning(f"No strategy configuration found for {pair}")
            return

        # Group strategies by timeframe to minimize data fetching
        # Format: { "1h": ["strat1", "strat2"], "15m": ["strat3"] }
        timeframe_groups = {}
        for config in configs:
            tf = config.get("timeframe")
            strat = config.get("strategy")
            if tf and strat:
                timeframe_groups.setdefault(tf, [])
                if strat not in timeframe_groups[tf]:
                    timeframe_groups[tf].append(strat)

        # Iterate through each timeframe group
        for tf, strat_names in timeframe_groups.items():
            logger.info(f"[{pair}] Fetching {tf} data for strategies: {strat_names}")

            # Fetch data once per timeframe (limit 500 for indicators)
            try:
                df = self.broker.fetch_ohlcv(pair, timeframe=tf, limit=500)
            except Exception as e:
                logger.error(f"Failed to fetch data for {pair} ({tf}): {e}")
                continue

            # Run each strategy for this timeframe
            strategy_results = []
            for strat_name in strat_names:
                strategy = self.strategies_map.get(strat_name)
                if not strategy:
                    logger.warning(f"Strategy '{strat_name}' not found for {pair}. Skipping.")
                    continue

                try:
                    # Pass a copy to avoid indicator pollution across strategies
                    signal = strategy.analyse(df.copy(), pair)
                    strategy_results.append({"name": strat_name, "signal": signal})
                except Exception as e:
                    logger.error(f"Error running strategy {strat_name} on {pair}: {e}")
                    continue

            # ─── Confluence Logic ───
            if settings.ENABLE_CONFLUENCE:
                buys = [r for r in strategy_results if r["signal"].signal == "BUY"]
                sells = [r for r in strategy_results if r["signal"].signal == "SELL"]
                
                # Log detailed voting results for user transparency
                vote_details = [f"{r['name']}={r['signal'].signal}" for r in strategy_results]
                logger.info(f"[{pair}] {tf} Strategy Votes: {', '.join(vote_details)}")

                # Determine requirement: min(configured, global_min) or override
                confluence_threshold = min_confluence_override if min_confluence_override is not None else settings.MIN_CONFLUENCE
                
                # Calculate Base Consensus (excluding required strategies if needed, but for now count all)
                # Actually, if we have required strategies, they MUST be present in the confirming set.
                
                req_count = min(len(strat_names), confluence_threshold)
                if len(strat_names) == 1: 
                    req_count = 1
                
                final_signal_data = None
                contributors = []
                
                # Check for strict requirements first
                buy_valid = True
                sell_valid = True
                
                for req in required_strategies:
                    # Check if required strategy signaled BUY
                    if not any(r["name"] == req and r["signal"].signal == "BUY" for r in strategy_results):
                        buy_valid = False
                    # Check if required strategy signaled SELL
                    if not any(r["name"] == req and r["signal"].signal == "SELL" for r in strategy_results):
                        sell_valid = False
                
                if buy_valid and len(buys) >= req_count:
                    final_signal_data = buys[0]
                    contributors = [b["name"] for b in buys]
                    logger.info(f"[{pair}] {tf} Confluence BUY Confirmed! ({len(buys)}/{len(strat_names)} agreed: {contributors})")
                elif sell_valid and len(sells) >= req_count:
                    final_signal_data = sells[0]
                    contributors = [s["name"] for s in sells]
                    logger.info(f"[{pair}] {tf} Confluence SELL Confirmed! ({len(sells)}/{len(strat_names)} agreed: {contributors})")
                else:
                    if len(strat_names) > 1:
                        logger.info(f"[{pair}] {tf} No Confluence. (Buys={len(buys)}, Sells={len(sells)}, Required={req_count}, Strict={required_strategies})")
                
                trade_id = None
                acted_on_map = {} 
                block_reason = None
                risk_metrics = None
                can_trade = False
                
                if final_signal_data:
                    strat_name = final_signal_data["name"]
                    signal = final_signal_data["signal"]
                    
                    can_trade, block_reason, risk_metrics = self.risk.can_trade(pair, balance, strategy=strat_name)
                    
                    if can_trade:
                        trade_id, exec_fail_reason = self._execute_trade(signal, balance, strat_name, tf, df)
                        if trade_id:
                            for c_name in contributors:
                                acted_on_map[c_name] = True
                        else:
                            block_reason = exec_fail_reason or "Execution failed"
                    else:
                        logger.warning(f"[{pair}] Confluence Signal blocked — {block_reason}")
                
                # Save results
                for res in strategy_results:
                    s_name = res["name"]
                    sig = res["signal"]
                    is_acted = acted_on_map.get(s_name, False)
                    
                    metrics = None
                    skip = None
                    
                    if final_signal_data and s_name == final_signal_data["name"]:
                        metrics = risk_metrics
                        if not is_acted:
                            skip = block_reason
                    elif not is_acted:
                        # Logic for strategies that signaled but weren't the chosen one
                        if sig.signal != "NONE":
                            if not final_signal_data:
                                skip = f"Low Confluence ({len(buys) if sig.signal=='BUY' else len(sells)}/{req_count})"
                            elif s_name not in contributors:
                                skip = "Confluence Mismatch"
                            else:
                                # It was a contributor but we executed the 'final_signal_data' strategy instead
                                # (Merged into the main trade)
                                skip = f"Merged into {final_signal_data['name']}"

                    if sig.signal == "NONE":
                        logger.info(f"[{pair}] {tf} | {s_name}: No signal — {sig.reason}")
                    else:
                        self._save_signal_to_db(sig, s_name, tf, is_acted, trade_id, skip, metrics)

            else:
                # ─── Legacy (Individual) Logic ───
                for res in strategy_results:
                    strat_name = res["name"]
                    signal = res["signal"]
                    
                    if signal.signal != "NONE":
                        can_trade, block_reason, risk_metrics = self.risk.can_trade(pair, balance, strategy=strat_name)
                        trade_id = None
                        acted_on = False
                        skip_reason = None
                        
                        if can_trade:
                            trade_id, exec_fail_reason = self._execute_trade(signal, balance, strat_name, tf, df)
                            if trade_id:
                                acted_on = True
                            else:
                                skip_reason = exec_fail_reason or "Execution failed"
                        else:
                            skip_reason = block_reason
                            logger.warning(f"[{pair}] Signal {signal.signal} ({strat_name}) blocked — {block_reason}")
                            
                        self._save_signal_to_db(signal, strat_name, tf, acted_on, trade_id, skip_reason, risk_metrics)
                    else:
                        logger.info(f"[{pair}] {tf} | {strat_name}: No signal — {signal.reason}")

    # ─── Execute Trade ────────────────────────────────────
    def _validate_entry_conditions(self, pair: str, signal, df: pd.DataFrame = None) -> tuple[bool, str]:
        """
        Double-check market conditions before entry.
        Checks:
        1. Spread vs Profit (Don't trade if spread eats > 20% of profit)
        2. RSI Extremes (Don't buy top/sell bottom) - Global Filter (70/30)
        3. EMA 200 Trend Filter (Don't trade against major trend) - Global Filter
        """
        try:
            # Fetch real-time ticker
            ticker = self.broker.fetch_ticker(pair)
            bid = ticker.get("bid")
            ask = ticker.get("ask")
            
            if not bid or not ask:
                return True, "Ticker unavailable, skipping checks"

            # 1. Spread Check
            spread = ask - bid
            tp_dist = abs(signal.close - signal.take_profit)
            
            # If potential profit is small, spread matters a lot.
            if tp_dist > 0:
                spread_ratio = spread / tp_dist
                if spread_ratio > settings.MAX_SPREAD_PROFIT_RATIO:
                    return False, f"Spread ({spread:.5f}) is {spread_ratio*100:.1f}% of TP distance. Too expensive."

            # 2. RSI Extreme & EMA Trend Check (Safety)
            if df is not None and not df.empty:
                # Calculate RSI (14)
                rsi_ind = ta.momentum.RSIIndicator(close=df["close"], window=14)
                current_rsi = rsi_ind.rsi().iloc[-1]
                
                # Calculate EMA (200)
                ema_trend = ta.trend.EMAIndicator(close=df["close"], window=200)
                current_ema = ema_trend.ema_indicator().iloc[-1]
                current_close = df["close"].iloc[-1]

                # Safety Rules
                if signal.signal == "BUY":
                    if current_rsi > 70:
                        return False, f"RSI Overbought ({current_rsi:.1f} > 70) - Dangerous Buy"
                    if current_close < current_ema:
                        return False, f"Price below EMA 200 ({current_close:.2f} < {current_ema:.2f}) - Downtrend"

                if signal.signal == "SELL":
                    if current_rsi < 30:
                        return False, f"RSI Oversold ({current_rsi:.1f} < 30) - Dangerous Sell"
                    if current_close > current_ema:
                        return False, f"Price above EMA 200 ({current_close:.2f} > {current_ema:.2f}) - Uptrend"

            # Fallback (Legacy)
            elif hasattr(signal, "rsi"):
                rsi = getattr(signal, "rsi", None)
                if rsi:
                    if signal.signal == "BUY" and rsi > 70:
                        return False, f"RSI Overbought ({rsi:.1f}) - Dangerous Entry"
                    if signal.signal == "SELL" and rsi < 30:
                        return False, f"RSI Oversold ({rsi:.1f}) - Dangerous Entry"

            return True, "OK"

        except Exception as e:
            logger.warning(f"Entry validation error: {e}")
            return True, "Error bypassed" # Don't block on error, but log it

    def _execute_trade(self, signal, balance: float, strategy_name: str, timeframe: str, df: pd.DataFrame = None) -> tuple[str, str]:
        """Calculate position size and place the order. Returns (trade_id, failure_reason)."""
        pair        = signal.pair
        
        # ─── Pre-Entry Validation ───
        is_valid, reason = self._validate_entry_conditions(pair, signal, df)
        if not is_valid:
            logger.warning(f"[{pair}] Entry Validation Failed: {reason}")
            return None, reason

        sl_distance = abs(signal.close - signal.stop_loss)

        try:
            entry = float(signal.close)
            sl = float(signal.stop_loss)
            tp = float(signal.take_profit)
        except (TypeError, ValueError):
            logger.warning(f"[{pair}] Invalid entry/SL/TP values — trade skipped.")
            return None, "Invalid entry/SL/TP values"

        if signal.signal == "BUY":
            if not (sl < entry < tp):
                logger.warning(f"[{pair}] Invalid SL/TP for BUY — trade skipped.")
                return None, "Invalid SL/TP (sl < entry < tp failed)"
        elif signal.signal == "SELL":
            if not (tp < entry < sl):
                logger.warning(f"[{pair}] Invalid SL/TP for SELL — trade skipped.")
                return None, "Invalid SL/TP (tp < entry < sl failed)"

        # Check for Achievable TP (Double check entry)
        atr = getattr(signal, "atr", None)
        if atr and atr > 0:
             tp_dist = abs(entry - tp)
             if tp_dist > (4.0 * atr):
                  logger.warning(f"[{pair}] TP distance {tp_dist:.5f} is > 4x ATR ({atr:.5f}). Too far/unachievable. Skipping.")
                  return None, "TP > 4x ATR (Too Far)"

        # Ensure TP is not too close (Minimum Distance Check)
        if atr and atr > 0:
             tp_dist = abs(entry - tp)
             min_tp_dist = 0.5 * atr
             if tp_dist < min_tp_dist:
                  logger.warning(f"[{pair}] TP distance {tp_dist:.5f} is < 0.5x ATR ({min_tp_dist:.5f}). Too close/not worth risk. Skipping.")
                  return None, "TP < 0.5x ATR (Too Close)"


        quantity    = self.broker.calculate_quantity(
            pair        = pair,
            balance     = balance,
            risk_pct    = settings.RISK_PER_TRADE,
            sl_distance = sl_distance,
        )

        if quantity <= 0:
            logger.warning(f"[{pair}] Quantity calculated as 0 — trade skipped.")
            return None, "Quantity 0 (Risk too high or balance too low)"

        order_id = self.broker.place_order(
            pair        = pair,
            direction   = signal.signal,
            quantity    = quantity,
            price       = signal.close,
            stop_loss   = signal.stop_loss,
            take_profit = signal.take_profit,
        )

        if order_id:
            trade = TradeRepository.create_trade(
                pair        = pair,
                direction   = signal.signal,
                entry_price = signal.close,
                stop_loss   = signal.stop_loss,
                take_profit = signal.take_profit,
                quantity    = quantity,
                broker_order_id = order_id,
                mode        = self.mode,
                timeframe   = timeframe,
                strategy    = strategy_name,
            )
            logger.info(
                f"🚀 Trade executed | {signal.signal} {pair} @ {signal.close:.5f} | "
                f"Qty: {quantity} | SL: {signal.stop_loss:.5f} | TP: {signal.take_profit:.5f}"
            )

            # Send Notification
            try:
                msg = (
                    f"🚀 *Trade Executed*\n"
                    f"Pair: {pair}\n"
                    f"Direction: {signal.signal}\n"
                    f"Entry: {signal.close:.5f}\n"
                    f"SL: {signal.stop_loss:.5f}\n"
                    f"TP: {signal.take_profit:.5f}"
                )
                send_telegram_message(msg)
            except Exception as e:
                logger.error(f"Failed to send execution notification: {e}")

            return str(trade["_id"]), None
            
        return None, "Broker rejected order"
