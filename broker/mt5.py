import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict
from config.settings import settings
from utils.logger import logger

# Map standard timeframes to MT5 constants
TIMEFRAME_MAP = {
    "1m":  mt5.TIMEFRAME_M1,
    "5m":  mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h":  mt5.TIMEFRAME_H1,
    "4h":  mt5.TIMEFRAME_H4,
    "1d":  mt5.TIMEFRAME_D1,
}

# Common symbol mapping (Adjust as needed for your broker)
SYMBOL_MAP = {
    # Forex
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "USD/CHF": "USDCHF",
    "AUD/USD": "AUDUSD",
    "USD/CAD": "USDCAD",
    "NZD/USD": "NZDUSD",
    
    # Deriv Synthetics (Common names on Deriv MT5)
    # We map to the full name, but _get_mt5_symbol will also check aliases like "R_10"
    "Vol 10": "Volatility 10 Index",
    "Vol 25": "Volatility 25 Index",
    "Vol 50": "Volatility 50 Index",
    "Vol 75": "Volatility 75 Index",
    "Vol 100": "Volatility 100 Index",
    
    # Metals/Commodities
    "Gold": "XAUUSD",
    "Silver": "XAGUSD",
}

# Aliases for specific brokers (e.g. Deriv uses "R_10" for "Volatility 10 Index")
SYMBOL_ALIASES = {
    "Volatility 10 Index":  ["R_10", "1HZ10V"],
    "Volatility 25 Index":  ["R_25", "1HZ25V"],
    "Volatility 50 Index":  ["R_50", "1HZ50V"],
    "Volatility 75 Index":  ["R_75", "1HZ75V"],
    "Volatility 100 Index": ["R_100", "1HZ100V"],
    "EURUSD": ["EURUSD.m", "EURUSD.pro", "EURUSD.ecn"],
    "GBPUSD": ["GBPUSD.m", "GBPUSD.pro", "GBPUSD.ecn"],
}

class MT5Broker:
    """
    MetaTrader 5 Bridge Connector.
    Controls a local MT5 terminal instance.
    """

    def __init__(self):
        self.login    = settings.MT5_LOGIN
        self.password = settings.MT5_PASSWORD
        self.server   = settings.MT5_SERVER
        self.path     = settings.MT5_PATH
        self.mode     = settings.TRADE_MODE
        
        # Initialize connection
        if not self._initialize():
            raise RuntimeError("Failed to initialize MT5. Please check logs and .env configuration.")

    def _initialize(self) -> bool:
        """Initialize connection to MT5 terminal."""
        # Attempt to initialize
        if not mt5.initialize(path=self.path) if self.path else mt5.initialize():
            err_code, err_desc = mt5.last_error()
            logger.error(f"MT5 initialize() failed, error code = {err_code} ({err_desc})")
            if err_code == -10003: # MT5_INTERNAL_ERROR, often means not installed or path invalid
                logger.error("CRITICAL: MetaTrader 5 terminal not found or not installed.")
                logger.error("1. Please download and install MT5 from your broker (e.g., Deriv).")
                logger.error("2. If installed in a custom location, set MT5_PATH in .env")
            return False

        # Log terminal info for debugging immediately after initialize
        terminal_info = mt5.terminal_info()
        if terminal_info:
            logger.info(f"MT5 Terminal Path: {terminal_info.path}")
            logger.info(f"MT5 Terminal Name: {terminal_info.name}")
            logger.info(f"MT5 Connected: {terminal_info.connected}")

            if not terminal_info.trade_allowed:
                logger.error("=" * 60)
                logger.error("CRITICAL ERROR: Algo Trading is DISABLED in MetaTrader 5!")
                logger.error("Please enable 'Algo Trading' in your MT5 toolbar (Green Play Button).")
                logger.error("The bot cannot place orders until this is enabled.")
                logger.error("=" * 60)
                return False
        else:
            logger.error("Failed to get terminal info immediately after initialization")

        # If login credentials provided, try to login
        if self.login and self.password and self.server:
            authorized = mt5.login(self.login, password=self.password, server=self.server)
            if authorized:
                logger.info(f"Connected to MT5 account #{self.login} on {self.server}")
            else:
                logger.error(f"Failed to connect to MT5 account #{self.login}, error code: {mt5.last_error()}")
                logger.error("Please verify MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER in .env")
                return False
        else:
            logger.info("MT5 initialized without specific login (using current terminal state)")
            logger.warning("No credentials provided in .env - assuming MT5 terminal is already logged in.")
        
        return True

    def _get_mt5_symbol(self, pair: str) -> str:
        """Convert standard pair to MT5 symbol (e.g., 'EUR/USD' -> 'EURUSD')."""
        # Check explicit mapping first
        if pair in SYMBOL_MAP:
            symbol = SYMBOL_MAP[pair]
        else:
            # Default: remove slash
            symbol = pair.replace("/", "")
        
        # Check if symbol exists in Market Watch
        info = mt5.symbol_info(symbol)
        
        # If not found, try aliases
        if info is None:
            # Check known aliases
            if symbol in SYMBOL_ALIASES:
                for alias in SYMBOL_ALIASES[symbol]:
                    if mt5.symbol_info(alias):
                        # Ensure alias is selected
                        mt5.symbol_select(alias, True)
                        return alias

            # Try appending suffix if needed (common in some brokers)
            for suffix in [".m", ".ecn", ".pro"]:
                test = symbol + suffix
                if mt5.symbol_info(test):
                    mt5.symbol_select(test, True)
                    return test
            
            # If still not found, log warning and return original
            logger.warning(f"Symbol {symbol} not found in MT5 Market Watch. Ensure it is visible.")
            return symbol
            
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                logger.error(f"Symbol {symbol} found but failed to select/enable in Market Watch")
        
        return symbol

    def _get_mt5_timeframe(self, timeframe: str):
        if timeframe not in TIMEFRAME_MAP:
            raise ValueError(f"Timeframe {timeframe} not supported by MT5 connector")
        return TIMEFRAME_MAP[timeframe]

    def test_connection(self) -> bool:
        """Test API connection."""
        if not mt5.terminal_info():
            return self._initialize()
        return True

    # ─── Market Data ──────────────────────────────────────
    def fetch_ohlcv(self, pair: str, timeframe: str = "1h", limit: int = 200) -> pd.DataFrame:
        symbol = self._get_mt5_symbol(pair)
        tf     = self._get_mt5_timeframe(timeframe)
        
        # Copy rates from current time backwards
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, limit)
        
        if rates is None or len(rates) == 0:
            logger.error(f"Failed to fetch rates for {symbol}: {mt5.last_error()}")
            raise ValueError(f"No data for {symbol}")

        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df["timestamp"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("timestamp", inplace=True)
        
        # Rename columns to match standard format
        df.rename(columns={
            "open": "open", 
            "high": "high", 
            "low": "low", 
            "close": "close", 
            "tick_volume": "volume"
        }, inplace=True)
        
        return df[["open", "high", "low", "close", "volume"]]

    def fetch_ticker(self, pair: str) -> dict:
        symbol = self._get_mt5_symbol(pair)
        tick   = mt5.symbol_info_tick(symbol)
        
        if tick is None:
            logger.error(f"Failed to get tick for {symbol}")
            return {}
            
        return {
            "pair": pair,
            "bid":  tick.bid,
            "ask":  tick.ask,
            "last": tick.last,
            "time": datetime.fromtimestamp(tick.time),
        }

    # ─── Account ──────────────────────────────────────────
    def get_balance(self) -> float:
        info = mt5.account_info()
        if info is None:
            logger.error("Failed to get account info")
            return 0.0
        return info.balance

    def get_open_positions(self) -> list:
        """Get all open positions from MT5."""
        positions = mt5.positions_get()
        if positions is None:
            return []
        
        results = []
        for p in positions:
            results.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type":   "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "price_current": p.price_current,
                "profit": p.profit,
                "time": datetime.fromtimestamp(p.time),
            })
        return results

    def get_closed_trade_info(self, ticket: int) -> Optional[dict]:
        """
        Get exit details for a closed position by its ticket.
        Returns dict with exit_price, exit_time, pnl, reason.
        """
        # Fetch deals for this position ticket
        # history_deals_get(position=ticket) returns all deals related to this position lifecycle
        deals = mt5.history_deals_get(position=ticket)
        
        if not deals or len(deals) == 0:
            logger.warning(f"No history deals found for position ticket {ticket}")
            return None
            
        # The last deal is usually the exit (Entry In -> ... -> Entry Out)
        # We look for entry_out or entry_out_by
        exit_deal = None
        total_profit = 0.0
        
        for deal in deals:
            total_profit += deal.profit + deal.swap + deal.commission
            if deal.entry == mt5.DEAL_ENTRY_OUT or deal.entry == mt5.DEAL_ENTRY_OUT_BY:
                exit_deal = deal
        
        if not exit_deal:
            # It might be closed but we missed the OUT deal? Or partial close?
            # If no OUT deal, maybe it's not closed? But the caller says it's not in open positions.
            # Fallback to the last deal
            exit_deal = deals[-1]

        # Determine exit reason
        reason = "Manual/Unknown"
        if exit_deal.reason == mt5.DEAL_REASON_SL:
            reason = "SL"
        elif exit_deal.reason == mt5.DEAL_REASON_TP:
            reason = "TP"
        elif exit_deal.reason == mt5.DEAL_REASON_CLIENT:
            reason = "Manual"
        elif exit_deal.reason == mt5.DEAL_REASON_EXPERT:
            reason = "Strategy/Expert"

        return {
            "exit_price": exit_deal.price,
            "exit_time":  datetime.fromtimestamp(exit_deal.time),
            "pnl":        total_profit,
            "reason":     reason,
        }

    # ─── Trading ──────────────────────────────────────────
    def calculate_quantity(
        self,
        pair: str,
        balance: float,
        risk_pct: float,
        sl_distance: float,
    ) -> float:
        """
        Calculate lot size for MT5.
        """
        if sl_distance <= 0:
            return 0.0

        risk_amount = balance * risk_pct
        
        # Get symbol info for tick value and contract size
        symbol = self._get_mt5_symbol(pair)
        info   = mt5.symbol_info(symbol)
        
        if info is None:
            logger.warning(f"Cannot calculate quantity: {symbol} info not found")
            return 0.01

        # Safety: Check if trade_tick_value is valid
        if info.trade_tick_value == 0 or info.trade_tick_size == 0:
            logger.warning(f"Zero tick value/size for {symbol}, defaulting to 0.01")
            return 0.01

        # Calculate Loss per Lot
        # Loss = (SL_Distance / TickSize) * TickValue
        loss_per_lot = (sl_distance / info.trade_tick_size) * info.trade_tick_value

        # Log calculation details for debugging
        logger.info(f"Size Calc [{symbol}]: Bal={balance}, Risk={risk_amount:.2f}, SL_Dist={sl_distance}, TickSize={info.trade_tick_size}, TickVal={info.trade_tick_value}")
        logger.info(f"Size Calc [{symbol}]: Loss/Lot={loss_per_lot:.2f}")

        if loss_per_lot == 0:
            return 0.01
            
        lots = risk_amount / loss_per_lot

        # 2. Leverage/Balance Safety Check
        # Max Notional = Balance * 200
        contract_size = info.trade_contract_size if info.trade_contract_size else 1.0
        current_price = info.bid if info.bid > 0 else 1.0
        
        MAX_LEVERAGE = 200.0
        max_lots_leverage = (balance * MAX_LEVERAGE) / (contract_size * current_price)
        
        if lots > max_lots_leverage:
             logger.warning(f"[{symbol}] Capping lots {lots:.2f} -> {max_lots_leverage:.2f} to respect Max Leverage {MAX_LEVERAGE}x")
             lots = max_lots_leverage
        
        # Normalize volume
        step = info.volume_step
        if step > 0:
            lots = round(lots / step) * step
            
        lots = max(lots, info.volume_min)
        lots = min(lots, info.volume_max)

        # SAFETY CAPS per Symbol (Hard Limits)
        # Includes aliases for Deriv (R_xx)
        # UPDATED: Vol 75 capped at 0.01 per user request to avoid excessive risk
        MAX_LOTS = {
            "Volatility 75 Index": 0.01, "R_75": 0.01, "1HZ75V": 0.01, # Reduced from 0.05
            "Volatility 50 Index": 4.0,  "R_50": 4.0,  "1HZ50V": 4.0,
            "Volatility 100 Index": 1.0, "R_100": 1.0, "1HZ100V": 1.0,
            "Volatility 10 Index": 1.0,  "R_10": 1.0,  "1HZ10V": 1.0,
            "Volatility 25 Index": 1.0,  "R_25": 1.0,  "1HZ25V": 1.0,
            "EURUSD": 5.0,
            "XAUUSD": 2.0
        }

        # Check exact symbol or mapped name
        limit = MAX_LOTS.get(symbol, 5.0)
        
        # Also check if the pair name itself is in the map (e.g. "Vol 75")
        # But pair is usually "Volatility 75 Index" from settings.
        
        if lots > limit:
             logger.warning(f"Capping {symbol} lot size from {lots} to {limit} for safety.")
             lots = limit
        
        return float(f"{lots:.5f}")

    def place_order(
        self,
        pair: str,
        direction: str,
        quantity: float,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[str]:
        symbol = self._get_mt5_symbol(pair)
        action = mt5.TRADE_ACTION_DEAL
        type_  = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        
        # Determine correct filling mode
        filling_mode = mt5.ORDER_FILLING_FOK  # Default attempt
        symbol_info = mt5.symbol_info(symbol)
        
        if symbol_info:
            # Check filling modes supported by symbol
            # flags: 1=FOK, 2=IOC, 3=FOK+IOC
            # Note: MT5 python lib might return different bitmask structure, 
            # but usually we check symbol_info.filling_mode
            
            # Safe fallback logic:
            # Some brokers require ORDER_FILLING_RETURN (0) or others.
            # We will try to detect.
            pass

        request = {
            "action":       action,
            "symbol":       symbol,
            "volume":       quantity,
            "type":         type_,
            "price":        price,
            "deviation":    20,
            "magic":        123456,
            "comment":      "Trae Trading Bot",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC, # Try IOC first, if fails we might need logic to retry
        }
        
        if stop_loss:
            request["sl"] = stop_loss
        if take_profit:
            request["tp"] = take_profit
            
        result = mt5.order_send(request)
        
        # If failed with unsupported filling mode, try FOK or RETURN
        if result.retcode == 10030: # Unsupported filling mode
            logger.warning("Order failed with filling mode IOC, retrying with FOK...")
            request["type_filling"] = mt5.ORDER_FILLING_FOK
            result = mt5.order_send(request)
        
        if result.retcode == 10030: # Still failing
             logger.warning("Order failed with filling mode FOK, retrying with RETURN...")
             request["type_filling"] = mt5.ORDER_FILLING_RETURN
             result = mt5.order_send(request)
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed: {result.comment} (Code: {result.retcode})")
            return None
            
        logger.info(f"Order placed on MT5: #{result.order}")
        return str(result.order)

    def close_order(self, order_id: str, exit_price: float) -> bool:
        """
        Close a position by opening an opposing trade or using close_by (if hedging).
        For simplicity, we assume we close the position by ticket if possible, 
        or just send an opposing order if we don't track the ticket perfectly.
        
        Wait, order_id returned by place_order is the order ticket. 
        But we need the POSITION ticket to close it.
        MT5 distinguishes orders and positions.
        """
        # Try to find the position matching the magic number and symbol
        # Or if we stored the position ID. 
        # The 'order_id' we return above is likely the order ticket, which becomes a position.
        # Usually position ticket == order ticket for the first order.
        
        try:
            # Check if order_id is a valid integer (MT5 ticket)
            if not str(order_id).isdigit():
                logger.warning(f"Invalid order ID format: {order_id}. Skipping close attempt.")
                return False

            position_id = int(order_id)
            positions = mt5.positions_get(ticket=position_id)
            
            if not positions:
                logger.warning(f"Position {position_id} not found in open positions.")
                return False
                
            pos = positions[0]
            
            # Close it
            type_ = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY # 0 is BUY, 1 is SELL
            
            # Get current price
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                logger.error(f"Failed to get tick for {pos.symbol}")
                return False
                
            price = tick.bid if type_ == mt5.ORDER_TYPE_SELL else tick.ask
            
            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       pos.volume,
                "type":         type_,
                "position":     position_id,
                "price":        price,
                "deviation":    20,
                "magic":        123456,
                "comment":      "Close by Bot",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC, # Try IOC first
            }
            
            result = mt5.order_send(request)
            
            # Filling mode retry logic for closing
            if result.retcode == 10030: # Unsupported filling mode
                 request["type_filling"] = mt5.ORDER_FILLING_FOK
                 result = mt5.order_send(request)
                 
            if result.retcode == 10030: 
                 request["type_filling"] = mt5.ORDER_FILLING_RETURN
                 result = mt5.order_send(request)

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Failed to close position {position_id}: {result.comment} ({result.retcode})")
                return False
            else:
                logger.info(f"Position {position_id} closed successfully")
                return True
                
        except Exception as e:
            logger.error(f"Error closing order {order_id}: {e}")
            return False
