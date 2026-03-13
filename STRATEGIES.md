# Trading Strategies

This bot supports multiple trading strategies designed for different market conditions.

## 1. EMA Crossover + RSI (Trend Following)
**Best for:** Strong trending markets (Forex majors, Trending Volatility Indices).
**Logic:**
- **Entry:** Fast EMA (9) crosses Slow EMA (21).
- **Confirmation:**
  - **RSI:** Must be > 55 (Buy) or < 45 (Sell) to confirm momentum.
  - **Trend Filter:** Price must be above EMA 200 (Buy) or below EMA 200 (Sell).
  - **ADX:** Trend strength must be > 25.
- **Exit:** Fixed SL/TP based on ATR.

## 2. Bollinger Breakout (Volatility Breakout)
**Best for:** Explosive moves after consolidation (Volatility Indices).
**Logic:**
- **Entry:** Price breaks above Upper Bollinger Band (Buy) or below Lower Bollinger Band (Sell).
- **Confirmation:**
  - **Bandwidth Expansion:** The bands must be widening (Bandwidth > 20-period average), indicating increasing volatility.
- **Exit:**
  - **SL:** ATR-based (e.g., 2.0x ATR).
  - **TP:** ATR-based (e.g., 4.0x ATR).

## 3. Mean Reversion (Bollinger + RSI)
**Best for:** Ranging/Choppy markets (Low ADX).
**Logic:**
- **Entry:** Price touches Lower Band (Buy) or Upper Band (Sell).
- **Confirmation:**
  - **RSI:** Must be Oversold < 30 (Buy) or Overbought > 70 (Sell).
  - **Market Condition:** ADX must be < 25 (confirming no strong trend).
- **Exit:**
  - **TP:** Middle Bollinger Band (Mean).
  - **SL:** Distance to opposite band or calculated risk.

## 4. Optimization Results & Configuration

Based on backtesting optimization (March 2026), the following strategies are assigned to each Volatility Index for maximum profitability:

| Index | Strategy | Timeframe | Notes |
|-------|----------|-----------|-------|
| **Vol 10** | Bollinger Breakout | 1h | Best performer |
| **Vol 25** | Bollinger Breakout | 1h | **Highest Profit (38%+)** |
| **Vol 50** | Bollinger Breakout | 15m | Strong breakout performance |
| **Vol 75** | Bollinger Breakout | 15m | Consistent winner |
| **Vol 100** | Mean Reversion | 1h | Ranging behavior detected |

These mappings are configured in `config/settings.py` and applied automatically by the trading engine.

## 5. Running Backtests
Run the optimization script to test all strategies on all Volatility indices:
```bash
python optimize_volatility.py
```
This will output a summary table showing which strategy works best for each index.
