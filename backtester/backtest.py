"""
backtester/backtest.py
───────────────────────
Backtesting engine using backtrader.
Tests the Strong Trend Following strategy against historical data.

Usage:
  python backtester/backtest.py --pair EUR/USD --timeframe 1h --days 180
"""

import argparse
import sys
import os
import matplotlib
matplotlib.use("Agg")   # Non-interactive backend — saves chart to file
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt
import backtrader.analyzers as btanalyzers
import pandas as pd

from broker.connector import ForexBroker
from config.settings import settings
from utils.logger import logger


# ─── Backtrader Strategies ──────────────────────────────────

class TrendFollowing_BT(bt.Strategy):
    """
    Backtrader implementation of the Strong Trend Following strategy.
    """

    params = (
        ("ema_fast",    20),
        ("ema_medium",  50),
        ("ema_slow",    200),
        ("adx_period",  14),
        ("adx_threshold", 25),
        ("rsi_period",  14),
        ("atr_period",  14),
        ("sl_mult",     settings.ATR_MULTIPLIER_SL),
        ("tp_mult",     settings.ATR_MULTIPLIER_TP),
        ("risk_pct",    settings.RISK_PER_TRADE),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.p.ema_fast)
        self.ema_medium = bt.indicators.EMA(self.data.close, period=self.p.ema_medium)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.p.ema_slow)
        
        self.adx      = bt.indicators.ADX(self.data,       period=self.p.adx_period)
        self.rsi      = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr      = bt.indicators.ATR(self.data,       period=self.p.atr_period)

        self.order      = None
        self.trade_log  = []

    def log(self, msg):
        dt = self.datas[0].datetime.date(0)
        logger.debug(f"[Backtest {dt}] {msg}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                "pnl":      round(trade.pnl, 4),
                "pnlcomm":  round(trade.pnlcomm, 4),
            })
            self.log(f"Trade closed | PnL: {trade.pnl:.4f}")

    def next(self):
        if self.position:
            # Check for Strategy Exit (Reversal)
            close = self.data.close[0]
            ema20 = self.ema_fast[0]
            ema50 = self.ema_medium[0]
            
            if self.position.size > 0:  # Long
                if close < ema50 or ema20 < ema50:
                    self.close()
                    self.log("Exit: Trend Weakened (Long)")
            else:  # Short
                if close > ema50 or ema20 > ema50:
                    self.close()
                    self.log("Exit: Trend Weakened (Short)")
            return

        # Entry Logic
        close = self.data.close[0]
        ema20 = self.ema_fast[0]
        ema50 = self.ema_medium[0]
        ema200 = self.ema_slow[0]
        adx = self.adx[0]
        rsi = self.rsi[0]
        atr = self.atr[0]

        is_uptrend = (ema20 > ema50 > ema200) and (close > ema20)
        is_downtrend = (ema20 < ema50 < ema200) and (close < ema20)
        is_strong = adx > self.p.adx_threshold

        if is_uptrend and is_strong and rsi > 50:
            # Buy
            sl = close - (atr * self.p.sl_mult)
            tp = close + (atr * self.p.tp_mult)
            self.buy_bracket(limitprice=tp, stopprice=sl)
            self.log(f"BUY signal | Price={close:.5f} | SL={sl:.5f} | TP={tp:.5f}")
            
        elif is_downtrend and is_strong and rsi < 50:
            # Sell
            sl = close + (atr * self.p.sl_mult)
            tp = close - (atr * self.p.tp_mult)
            self.sell_bracket(limitprice=tp, stopprice=sl)
            self.log(f"SELL signal | Price={close:.5f} | SL={sl:.5f} | TP={tp:.5f}")


# ─── Main Runner ────────────────────────────────────────────

def run_backtest(pair: str = "EUR/USD", timeframe: str = "1h", days: int = 60, starting_cash: float = 1000.0, strategy_name: str = "trend_following"):
    """Fetch data from MT5 and run backtest."""
    broker = ForexBroker()
    
    # 1. Fetch Data
    logger.info(f"Fetching {days} days of data for {pair} ({timeframe})...")
    try:
        # Limit estimate based on timeframe
        minutes_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
        limit = (24 * 60 // minutes_map.get(timeframe, 60)) * days
        
        df = broker.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        if df.empty:
            logger.error("No data found for backtest.")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        return None

    # 2. Setup Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(starting_cash)
    cerebro.broker.setcommission(commission=0.0001) # Approx 1 pip spread

    # Add Data
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # Add Strategy
    cerebro.addstrategy(TrendFollowing_BT)

    # Add Analyzers
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(btanalyzers.DrawDown,    _name='drawdown')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')

    # 3. Run
    logger.info(f"Starting Backtest | Cash: ${starting_cash:.2f}")
    results = cerebro.run()
    strat = results[0]

    # 4. Results
    final_value = cerebro.broker.getvalue()
    profit      = final_value - starting_cash
    profit_pct  = (profit / starting_cash) * 100
    
    analysis_trades = strat.analyzers.trades.get_analysis()
    total_trades = analysis_trades.total.total if 'total' in analysis_trades else 0
    win_rate     = (analysis_trades.won.total / total_trades * 100) if total_trades > 0 else 0

    print("\n" + "=" * 40)
    print(f"  BACKTEST RESULTS: {pair} ({timeframe})")
    print("=" * 40)
    print(f"  Starting Balance : ${starting_cash:.2f}")
    print(f"  Final Balance    : ${final_value:.2f}")
    print(f"  Net Profit       : ${profit:.2f} ({profit_pct:.2f}%)")
    print(f"  Total Trades     : {total_trades}")
    print(f"  Win Rate         : {win_rate:.1f}%")
    print(f"  Max Drawdown     : {strat.analyzers.drawdown.get_analysis().max.drawdown:.2f}%")
    print(f"  Sharpe Ratio     : {strat.analyzers.sharpe.get_analysis()['sharperatio'] or 0:.2f}")
    print("=" * 40 + "\n")

    # 5. Save Plot
    try:
        plot_path = f"backtest_{pair.replace('/', '_')}_{timeframe}.png"
        cerebro.plot(style='candlestick', savefig=True, filename=plot_path)
        logger.info(f"Backtest chart saved to {plot_path}")
    except Exception as e:
        logger.warning(f"Failed to save plot: {e}")

    return {
        "pair": pair,
        "profit_pct": profit_pct,
        "total_trades": total_trades,
        "win_rate": win_rate
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest Trading Bot")
    parser.add_argument("--pair",      type=str, default="EUR/USD", help="Trading pair (e.g. EUR/USD)")
    parser.add_argument("--timeframe", type=str, default="1h",      help="Timeframe (e.g. 1h, 15m)")
    parser.add_argument("--days",      type=int, default=60,        help="Number of days to test")
    parser.add_argument("--cash",      type=float, default=1000.0,  help="Starting cash")
    
    args = parser.parse_args()
    run_backtest(pair=args.pair, timeframe=args.timeframe, days=args.days, starting_cash=args.cash)
