"""
broker/connector.py
───────────────────
Deriv WebSocket API broker connector.
Handles:
  - WebSocket connection and authentication
  - Fetching OHLCV (candle) data via ticks_history
  - Fetching account balance
  - Placing and cancelling orders (buy/sell contracts)
  - Paper trading simulation

Deriv API docs: https://api.deriv.com
WebSocket endpoint: wss://ws.binaryws.com/websockets/v3
"""

import json
import time
import asyncio
import websocket
import pandas as pd
from datetime import datetime
from typing import Optional
from config.settings import settings
from utils.logger import logger


# ─── Deriv Pair Mapping ───────────────────────────────────
# Deriv uses its own symbol names — map standard Forex to Deriv symbols
PAIR_MAP = {
    # Forex
    "EUR/USD": "frxEURUSD",
    "GBP/USD": "frxGBPUSD",
    "USD/JPY": "frxUSDJPY",
    "USD/CHF": "frxUSDCHF",
    "AUD/USD": "frxAUDUSD",
    "USD/CAD": "frxUSDCAD",
    "NZD/USD": "frxNZDUSD",
    "EUR/GBP": "frxEURGBP",
    "EUR/JPY": "frxEURJPY",
    "GBP/JPY": "frxGBPJPY",
    # Synthetics (Volatility Indices)
    "Vol 10": "R_10",
    "Vol 25": "R_25",
    "Vol 50": "R_50",
    "Vol 75": "R_75",
    "Vol 100": "R_100",
    "Vol 10 (1s)": "1HZ10V",
    "Vol 25 (1s)": "1HZ25V",
    "Vol 50 (1s)": "1HZ50V",
    "Vol 75 (1s)": "1HZ75V",
    "Vol 100 (1s)": "1HZ100V",
    # Jump Indices
    "Jump 10": "JD10",
    "Jump 25": "JD25",
    "Jump 50": "JD50",
    "Jump 75": "JD75",
    "Jump 100": "JD100",
    # Gold/Indices
    "Gold": "frxXAUUSD",
    "US 500": "SPCUSD",
}

# Deriv timeframe mapping
TIMEFRAME_MAP = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "30m": 1800,
    "1h":  3600,
    "4h":  14400,
    "1d":  86400,
}


class DerivBroker:
    """
    Deriv WebSocket API broker connector.
    Supports both paper (simulated) and live modes.
    Account type VRTC = Virtual/Demo (paper trading).
    """

    WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

    def __init__(self):
        self.api_token      = settings.EXCHANGE_API_KEY
        self.account_id     = settings.EXCHANGE_API_SECRET
        self.mode           = settings.TRADE_MODE
        self._paper_balance = 10000.0
        self._paper_trades  = {}
        self._virtual       = settings.EXCHANGE_SANDBOX

        logger.info(
            f"Deriv broker initialised | "
            f"Mode: {self.mode.upper()} | "
            f"Account: {self.account_id} | "
            f"Virtual: {self._virtual}"
        )

    # ─── WebSocket Helper ─────────────────────────────────
    def _send_request(self, payload: dict) -> dict:
        """
        Send a synchronous WebSocket request to Deriv API.
        Handles authentication automatically if required.
        """
        result    = {}
        error_msg = {}
        
        # Determine if we need to authenticate first
        # Public calls that usually don't need auth
        # Note: We authenticate 'ticks_history' to avoid rate limits/errors on public nodes
        public_cmds = ["time", "ping", "website_status", "active_symbols"]
        cmd = next(iter(payload))
        needs_auth = cmd not in public_cmds and self.api_token

        def on_message(ws, message):
            nonlocal result, error_msg
            data = json.loads(message)
            
            if "error" in data:
                # If we get an error during auth, we should stop
                error_msg = data["error"]
                ws.close()
                return

            msg_type = data.get("msg_type")
            
            # If we just got the authorize response, now send the actual payload
            if msg_type == "authorize":
                ws.send(json.dumps(payload))
                return

            # Otherwise, this is the response we wanted
            result = data
            ws.close()

        def on_error(ws, error):
            logger.error(f"Deriv WebSocket error: {error}")

        def on_open(ws):
            if needs_auth:
                # Send auth request first
                ws.send(json.dumps({"authorize": self.api_token}))
            else:
                # Send payload directly
                ws.send(json.dumps(payload))

        ws_app = websocket.WebSocketApp(
            self.WS_URL,
            on_open    = on_open,
            on_message = on_message,
            on_error   = on_error,
        )
        ws_app.run_forever()

        if error_msg:
            raise Exception(f"Deriv API error: {error_msg.get('message', error_msg)}")

        return result

    def _get_deriv_symbol(self, pair: str) -> str:
        """Convert standard Forex pair to Deriv symbol."""
        symbol = PAIR_MAP.get(pair)
        if not symbol:
            raise ValueError(
                f"Pair '{pair}' not supported. "
                f"Supported pairs: {list(PAIR_MAP.keys())}"
            )
        return symbol

    def _get_deriv_granularity(self, timeframe: str) -> int:
        """Convert timeframe string to Deriv granularity in seconds."""
        granularity = TIMEFRAME_MAP.get(timeframe)
        if not granularity:
            raise ValueError(
                f"Timeframe '{timeframe}' not supported. "
                f"Supported: {list(TIMEFRAME_MAP.keys())}"
            )
        return granularity

    # ─── Market Data ──────────────────────────────────────
    def fetch_ohlcv(
        self,
        pair: str,
        timeframe: str = "1h",
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data from Deriv.
        Uses ticks_history API with OHLC style.
        Returns DataFrame with columns: open, high, low, close, volume
        """
        symbol      = self._get_deriv_symbol(pair)
        granularity = self._get_deriv_granularity(timeframe)

        logger.debug(f"Fetching {limit} candles for {pair} ({symbol}) [{timeframe}]...")

        payload = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count":        limit,
            "end":          "latest",
            "granularity":  granularity,
            "style":        "candles",
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self._send_request(payload)
                candles  = response.get("candles", [])

                if not candles:
                    raise ValueError(f"No candle data returned for {pair}")

                df = pd.DataFrame(candles)
                df["timestamp"] = pd.to_datetime(df["epoch"], unit="s")
                df.set_index("timestamp", inplace=True)
                df = df.rename(columns={
                    "open":  "open",
                    "high":  "high",
                    "low":   "low",
                    "close": "close",
                })
                df["volume"] = 0.0   # Deriv doesn't provide volume for Forex
                df = df[["open", "high", "low", "close", "volume"]].astype(float)
                df.drop_duplicates(inplace=True)
                df.sort_index(inplace=True)

                logger.debug(f"Fetched {len(df)} candles for {pair} from {df.index[0]} to {df.index[-1]}")
                return df

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed to fetch OHLCV for {pair}: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch OHLCV for {pair} after {max_retries} attempts: {e}")
                    raise
                time.sleep(5)  # Increased delay for stability

    def fetch_ticker(self, pair: str) -> dict:
        """Get current price for a pair using latest tick."""
        symbol = self._get_deriv_symbol(pair)

        payload = {
            "ticks": symbol,
            "subscribe": 0,
        }

        try:
            # Use ticks_history with count=1 for latest price
            payload = {
                "ticks_history": symbol,
                "count":   1,
                "end":     "latest",
                "style":   "ticks",
            }
            response = self._send_request(payload)
            ticks    = response.get("history", {})
            prices   = ticks.get("prices", [])
            last     = float(prices[-1]) if prices else 0.0

            return {
                "pair": pair,
                "bid":  last,
                "ask":  last,
                "last": last,
                "time": datetime.utcnow(),
            }
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {pair}: {e}")
            raise

    # ─── Account ──────────────────────────────────────────
    def get_balance(self) -> float:
        """
        Get account balance from Deriv.
        For virtual accounts (VRTC), returns virtual balance.
        """
        try:
            payload  = {"balance": 1, "loginid": self.account_id}
            response = self._send_request(payload)
            balance  = response.get("balance", {})
            amount   = float(balance.get("balance", self._paper_balance))
            currency = balance.get("currency", "USD")
            logger.info(f"Deriv balance: {amount:.2f} {currency} (Account: {self.account_id})")
            return amount
        except Exception as e:
            logger.warning(f"Could not fetch live balance, using paper balance: {e}")
            return self._paper_balance

    def get_account_info(self) -> dict:
        """Get full account information."""
        try:
            payload  = {"get_account_status": 1}
            response = self._send_request(payload)
            return response.get("get_account_status", {})
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return {}

    # ─── Order Execution ──────────────────────────────────
    def place_order(
        self,
        pair: str,
        direction: str,
        quantity: float,
        price: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """
        Place a trade on Deriv.
        If TRADE_MODE is 'paper', simulate locally.
        Otherwise (live), send real orders to Deriv (works for Real and Demo accounts).
        """
        if self.mode == "paper":
            return self._paper_place_order(
                pair, direction, quantity, price, stop_loss, take_profit
            )
        return self._live_place_order(
            pair, direction, quantity, price, stop_loss, take_profit
        )

    def _paper_place_order(
        self,
        pair: str,
        direction: str,
        quantity: float,
        price: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """Simulate an order locally (paper trading)."""
        order_id = f"PAPER-{pair.replace('/', '')}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        cost     = quantity * price

        self._paper_trades[order_id] = {
            "order_id":    order_id,
            "pair":        pair,
            "direction":   direction,
            "quantity":    quantity,
            "entry_price": price,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "status":      "OPEN",
            "opened_at":   datetime.utcnow(),
        }

        logger.info(
            f"[PAPER] Order placed | {direction} {quantity:.4f} {pair} @ {price:.5f} | "
            f"SL: {stop_loss:.5f} | TP: {take_profit:.5f} | Cost: ${cost:.2f}"
        )
        return self._paper_trades[order_id]

    def _live_place_order(
        self,
        pair: str,
        direction: str,
        quantity: float,
        price: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """
        Place a real CFD/multiplier contract on Deriv.
        Uses the buy API with multiplier contracts for Forex.
        """
        symbol    = self._get_deriv_symbol(pair)
        side      = "CALL" if direction == "BUY" else "PUT"

        payload = {
            "buy": 1,
            "price": quantity,   # Stake amount in account currency
            "parameters": {
                "contract_type": side,
                "symbol":        symbol,
                "duration":      1,
                "duration_unit": "d",
                "basis":         "stake",
                "amount":        quantity,
                "currency":      "USD",
                "stop_loss":     abs(price - stop_loss),
                "take_profit":   abs(take_profit - price),
            }
        }

        try:
            response = self._send_request(payload)
            contract = response.get("buy", {})
            logger.info(f"[LIVE] Deriv order placed: {contract}")
            return contract
        except Exception as e:
            logger.error(f"Failed to place live order on Deriv: {e}")
            raise

    def close_order(self, order_id: str, exit_price: float) -> Optional[dict]:
        """Close a paper trade and calculate P&L."""
        trade = self._paper_trades.get(order_id)
        if not trade:
            logger.warning(f"Paper trade {order_id} not found.")
            return None

        entry = trade["entry_price"]
        qty   = trade["quantity"]

        if trade["direction"] == "BUY":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        trade["exit_price"] = exit_price
        trade["pnl"]        = pnl
        trade["status"]     = "CLOSED"
        trade["closed_at"]  = datetime.utcnow()
        self._paper_balance += pnl

        logger.info(
            f"[PAPER] Trade closed | {order_id} | "
            f"Exit: {exit_price:.5f} | PnL: ${pnl:.2f} | "
            f"Balance: ${self._paper_balance:.2f}"
        )
        return trade

    def calculate_quantity(
        self,
        pair: str,
        balance: float,
        risk_pct: float,
        sl_distance: float,
    ) -> float:
        """
        Calculate position size based on risk management.
        Formula: (balance × risk_pct) / sl_distance
        """
        if sl_distance <= 0:
            logger.warning("SL distance is 0 — cannot calculate quantity.")
            return 0.0

        risk_amount = balance * risk_pct
        quantity    = risk_amount / sl_distance

        logger.debug(
            f"Position size | balance=${balance:.2f} | "
            f"risk={risk_pct*100:.1f}% | risk_amount=${risk_amount:.2f} | "
            f"sl_dist={sl_distance:.5f} | qty={quantity:.4f}"
        )
        return round(quantity, 4)

    def test_connection(self) -> bool:
        """Test API connection and authentication."""
        try:
            payload  = {"ping": 1}
            response = self._send_request(payload)
            if response.get("ping") == "pong":
                logger.info("✅ Deriv API connection successful.")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Deriv connection test failed: {e}")
            return False



try:
    from broker.mt5 import MT5Broker
except ImportError:
    MT5Broker = None
    logger.warning("MetaTrader5 module not found. MT5 bridge will not work.")

# Select Broker based on settings
if settings.EXCHANGE_ID == "mt5":
    if MT5Broker:
        ForexBroker = MT5Broker
        logger.info("Using MetaTrader 5 Bridge Connector")
    else:
        logger.error("EXCHANGE_ID is 'mt5' but MetaTrader5 library is missing! Falling back to Deriv.")
        ForexBroker = DerivBroker
else:
    ForexBroker = DerivBroker
