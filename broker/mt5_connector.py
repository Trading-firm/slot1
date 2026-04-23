"""
broker/mt5_connector.py
────────────────────────
MT5 connection and all broker operations.
Handles: connect, fetch candles, place orders,
close orders, get balance, get open positions.
"""

import MetaTrader5 as mt5
import pandas as pd
from utils.logger import logger
from config.settings import settings


def connect() -> bool:
    if not mt5.initialize():
        logger.error(f"MT5 init failed: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info is None:
        logger.error("Could not retrieve account info")
        return False
    logger.info(
        f"MT5 Connected | Account: {info.login} | "
        f"Balance: ${info.balance:.2f} | Server: {info.server}"
    )
    return True


def disconnect():
    mt5.shutdown()
    logger.info("MT5 disconnected.")


def get_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


def fetch_candles(symbol: str, timeframe: int, count: int = 500) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        logger.warning(f"No candle data for {symbol}")
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={
        "open": "Open", "high": "High",
        "low":  "Low",  "close": "Close",
        "tick_volume": "Volume"
    }, inplace=True)
    return df


def resolve_symbol(candidates) -> str:
    """
    Given a single symbol name OR a list of candidates, return the first one
    that exists on the connected MT5 account (selecting it into Market Watch).
    Returns "" if none found.

    Use this when the same logical market has different names per broker / account
    type (e.g. BTCUSD on demo vs BTCUSDm on real micro account).
    """
    import MetaTrader5 as mt5
    if isinstance(candidates, str):
        candidates = [candidates]
    for name in candidates:
        info = mt5.symbol_info(name)
        if info is None:
            continue
        if not info.visible:
            mt5.symbol_select(name, True)
        return name
    return ""


def get_symbol_info(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.error(f"Symbol info not found: {symbol}")
    return info


def normalize_volume(symbol: str, volume: float) -> float:
    """
    Normalizes the volume according to the broker's requirements:
    1. Between volume_min and volume_max
    2. A multiple of volume_step
    """
    info = get_symbol_info(symbol)
    if info is None:
        return volume

    # Get broker limits
    v_min = info.volume_min
    v_max = info.volume_max
    v_step = info.volume_step

    # Clamp between min and max
    if volume < v_min:
        return v_min
    if volume > v_max:
        return v_max

    # Round to the nearest volume_step
    # Formula: round(volume / step) * step
    normalized = round(volume / v_step) * v_step
    
    # Determine number of decimals from step (e.g., 0.01 -> 2)
    import math
    decimals = max(0, int(-math.log10(v_step)))
    
    # Ensure we don't return 0.0 or something below min due to rounding
    return max(v_min, round(normalized, decimals))


def calculate_lot_size(
    symbol: str,
    balance: float,
    risk_pct: float,
    sl_distance: float,
) -> float:
    """
    Calculates lot size based on account risk.

    Formula: lot = (balance * risk_pct) / sl_distance
    For most CFDs/crypto, 1 lot moves $1 per $1 of price movement,
    so this gives the correct risk amount in account currency.

    The result is then normalized to the broker's volume requirements.
    If the computed lot falls below the broker minimum, the minimum is
    returned — but this means the actual risk will exceed risk_pct.
    """
    if sl_distance <= 0:
        logger.warning(f"[{symbol}] SL distance is zero — falling back to minimum lot")
        info = get_symbol_info(symbol)
        min_lot = info.volume_min if info else settings.MIN_LOT_SIZE
        return normalize_volume(symbol, min_lot)

    risk_amount = balance * risk_pct  # e.g. $90 * 0.01 = $0.90
    lot = risk_amount / sl_distance   # e.g. $0.90 / 500 = 0.0018 lots

    normalized = normalize_volume(symbol, lot)

    # Warn if minimum lot forces risk above target
    info = get_symbol_info(symbol)
    if info and normalized > lot:
        actual_risk = normalized * sl_distance
        actual_pct  = actual_risk / balance * 100
        logger.warning(
            f"[{symbol}] Minimum lot ({normalized}) exceeds risk target. "
            f"Actual risk: ${actual_risk:.2f} ({actual_pct:.1f}%) vs target {risk_pct*100:.1f}%"
        )

    return normalized


def _get_filling_mode(symbol: str) -> int:
    """Determine the correct filling mode for the symbol."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC

    # SYMBOL_FILLING_FOK = 1, SYMBOL_FILLING_IOC = 2
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    elif info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    
    return mt5.ORDER_FILLING_RETURN


def place_order(
    symbol: str,
    direction: str,
    lot_size: float,
    sl: float,
    tp: float,
    comment: str = "UnifiedBot",
) -> dict:
    """
    Place a market order with SL and TP.
    Returns order result dict.
    """
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        logger.error(f"Could not get tick/info for {symbol}")
        return {}

    digits = info.digits
    filling_mode = _get_filling_mode(symbol)
    price     = tick.ask if direction == "BUY" else tick.bid
    order_type= mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    # Validate stops_level
    min_dist = info.trade_stops_level * info.point
    if sl > 0:
        dist = abs(price - sl)
        if dist < min_dist:
            logger.warning(f"[{symbol}] SL {sl} too close to price {price}. Adjusting to min distance {min_dist}")
            if direction == "BUY":
                sl = price - min_dist - (info.point * 10) # add small buffer
            else:
                sl = price + min_dist + (info.point * 10)

    if tp > 0:
        dist = abs(price - tp)
        if dist < min_dist:
            logger.warning(f"[{symbol}] TP {tp} too close to price {price}. Adjusting to min distance {min_dist}")
            if direction == "BUY":
                tp = price + min_dist + (info.point * 10)
            else:
                tp = price - min_dist - (info.point * 10)

    # Ensure volume is normalized before sending
    lot_size = normalize_volume(symbol, lot_size)

    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      lot_size,
        "type":        order_type,
        "price":       round(price, digits),
        "sl":          round(sl, digits),
        "tp":          round(tp, digits),
        "deviation":   20,
        "magic":       20250301,
        "comment":     comment,
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling":filling_mode,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else f"None (Last Error: {mt5.last_error()})"
        comment = result.comment if result else "No comment"
        logger.error(f"Order failed for {symbol} | Code: {code} | Comment: {comment} | Price: {price} SL: {sl} TP: {tp}")
        return {}

    logger.info(
        f"Order placed | {direction} {symbol} | "
        f"Lot: {lot_size} | Price: {price:.5f} | "
        f"SL: {sl:.5f} | TP: {tp:.5f} | Ticket: {result.order}"
    )
    return {
        "ticket":    result.order,
        "price":     price,
        "lot_size":  lot_size,
        "direction": direction,
        "symbol":    symbol,
        "sl":        sl,
        "tp":        tp,
    }


def close_order(ticket: int, symbol: str, direction: str, lot_size: float) -> bool:
    """Close an open position by ticket number."""
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return False

    digits = info.digits
    filling_mode = _get_filling_mode(symbol)
    close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
    price      = tick.bid if direction == "BUY" else tick.ask

    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      lot_size,
        "type":        close_type,
        "position":    ticket,
        "price":       round(price, digits),
        "deviation":   20,
        "magic":       20250301,
        "comment":     "UnifiedBot-Close",
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling":filling_mode,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"Position closed | Ticket: {ticket} | {symbol}")
        return True

    logger.error(f"Failed to close ticket {ticket} | Code: {result.retcode if result else 'None'}")
    return False


def update_stops(ticket: int, symbol: str, sl: float, tp: float) -> bool:
    """Update SL and TP for an open position."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return False

    request = {
        "action":       mt5.TRADE_ACTION_SLTP,
        "symbol":       symbol,
        "position":     ticket,
        "sl":           round(sl, info.digits),
        "tp":           round(tp, info.digits),
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        return True
    
    logger.error(f"Failed to update stops for ticket {ticket} | Code: {result.retcode if result else 'None'}")
    return False


def get_open_positions(symbol: str = None) -> list:
    """Get all open positions, optionally filtered by symbol."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    result = []
    for p in positions:
        result.append({
            "ticket":    p.ticket,
            "symbol":    p.symbol,
            "direction": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "lot_size":  p.volume,
            "open_price":p.price_open,
            "sl":        p.sl,
            "tp":        p.tp,
            "profit":    p.profit,
            "comment":   p.comment,
        })
    return result
