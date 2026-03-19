# Trading Strategies

The bot is currently configured to use a single, high-conviction strategy focused on **Strong Trend Following**.

## 1. Strong Trend Following Strategy
**Best for:** Strongly trending markets (Forex majors, Volatility Indices).
**Logic:**
- **Entry (BUY):**
  - **Trend Alignment:** EMA(20) > EMA(50) > EMA(200).
  - **Price Position:** Current price is above EMA(20).
  - **Trend Strength:** ADX(14) > 25 (confirming a strong trend).
  - **Momentum:** RSI(14) > 50 (bullish momentum).
- **Entry (SELL):**
  - **Trend Alignment:** EMA(20) < EMA(50) < EMA(200).
  - **Price Position:** Current price is below EMA(20).
  - **Trend Strength:** ADX(14) > 25 (confirming a strong trend).
  - **Momentum:** RSI(14) < 50 (bearish momentum).

- **Risk Management:**
  - **Stop Loss:** ATR-based (default 1.5x ATR).
  - **Take Profit:** ATR-based (default 1.0x ATR).
  - **Asset Specifics:** Custom SL/TP multipliers for Volatility 10, 25, and 75 Indices.

- **Exit (Strategy-Based):**
  - **Reversal:** The trade is closed if the trend weakens (e.g., price crosses EMA 50 or EMA 20 crosses EMA 50).

## 2. Configuration
The strategy is managed via `config/settings.py`. All other strategies have been removed to ensure focus on strong trends and minimize losses from choppy market conditions.

- **Default Timeframe:** 1h
- **Confluence:** Disabled (Single strategy mode)
- **ADX Threshold:** 25.0

## 3. Running Backtests
To verify the performance of the Strong Trend Following strategy:
```bash
python main.py backtest
```
This will run the strategy against the configured trading pairs using historical data.
