# Unified Bot — MongoDB Database Structure

Database name: `unified_bot`

---

## Collections Overview

| Collection | Purpose |
|---|---|
| `trades` | Every trade opened and closed |
| `signals` | Every signal generated (acted on or skipped) |
| `daily_summary` | End of day performance snapshot |
| `bot_state` | Persistent key-value store for bot state |
| `market_performance` | Running win rate and PnL per market |

---

## Collection: `trades`

Every trade the bot opens is stored here. When MT5 closes it (via TP or SL), the document is updated with exit data.

```json
{
  "_id":          "ObjectId — auto generated",
  "symbol":       "Volatility 25 Index",
  "direction":    "BUY | SELL",
  "entry_price":  1234.56789,
  "sl":           1230.00000,
  "tp":           1242.00000,
  "lot_size":     0.01,
  "ticket":       123456789,
  "strategy":     "supertrend | ema_rsi",
  "timeframe":    "H1 | M30 | M5",
  "rsi_at_entry": 63.4,
  "atr_at_entry": 2.345,
  "ema_trend":    1232.45000,
  "status":       "OPEN | CLOSED",
  "exit_price":   1242.00000,
  "exit_reason":  "TP | SL | MANUAL",
  "pnl":          7.4400,
  "pnl_pct":      0.60,
  "entry_time":   "2026-03-01T10:30:00Z",
  "exit_time":    "2026-03-01T14:45:00Z"
}
```

**Indexes:**
- `status` — for fast open trade lookups
- `symbol` — for per-market filtering
- `ticket` — unique, for MT5 sync
- `entry_time` — for date range queries

---

## Collection: `signals`

Every signal the strategy engine generates is logged here — whether the bot acted on it or not. This lets you audit why trades were skipped.

```json
{
  "_id":          "ObjectId — auto generated",
  "symbol":       "Volatility 10 Index",
  "direction":    "BUY | SELL | NONE",
  "strategy":     "ema_rsi | supertrend",
  "timeframe":    "M5",
  "rsi":          64.2,
  "atr":          1.234,
  "close_price":  5678.90,
  "sl":           5672.00,
  "tp":           5690.00,
  "acted_on":     true,
  "skip_reason":  null,
  "created_at":   "2026-03-01T10:30:00Z"
}
```

**skip_reason examples:**
- `"Max open trades reached (4/4)"`
- `"Already have open trade on Volatility 25 Index"`
- `"RSI 45.2 not above 60"`
- `"Price below EMA100"`
- `"Market not active (ATR below average)"`
- `"Daily loss limit hit"`

**Indexes:**
- `symbol` — filter by market
- `created_at` — sort by time

---

## Collection: `daily_summary`

Updated at the end of every cycle. One document per day.

```json
{
  "_id":           "ObjectId — auto generated",
  "date":          "2026-03-01",
  "total_trades":  3,
  "winning_trades":2,
  "losing_trades": 1,
  "win_rate":      66.7,
  "total_pnl":     14.2200,
  "best_trade":    9.8800,
  "worst_trade":  -4.5600,
  "open_trades":   1,
  "updated_at":    "2026-03-01T23:59:00Z"
}
```

**Indexes:**
- `date` — unique, one document per day

---

## Collection: `bot_state`

Key-value store for persistent bot state. Survives restarts.

```json
{
  "_id":        "ObjectId — auto generated",
  "key":        "last_cycle | balance | daily_stop_hit",
  "value":      "2026-03-01T14:30:00 | 1024.50 | false",
  "updated_at": "2026-03-01T14:30:00Z"
}
```

**Current keys stored:**
- `last_cycle` — ISO timestamp of last completed cycle
- `balance` — last known account balance

**Indexes:**
- `key` — unique

---

## Collection: `market_performance`

Running lifetime performance per market. Updated every time a trade closes.

```json
{
  "_id":           "ObjectId — auto generated",
  "symbol":        "Volatility 100 Index",
  "total_trades":  24,
  "wins":          17,
  "losses":        7,
  "total_pnl":     84.3200,
  "created_at":    "2026-03-01T08:00:00Z",
  "updated_at":    "2026-03-05T16:22:00Z"
}
```

To calculate win rate from this document:
```
win_rate = (wins / total_trades) * 100
```

**Indexes:**
- `symbol` — unique per market

---

## Useful Queries (MongoDB Compass or mongosh)

**View all open trades:**
```js
db.trades.find({ status: "OPEN" })
```

**View today's closed trades:**
```js
db.trades.find({
  status: "CLOSED",
  exit_time: { $gte: new Date("2026-03-01") }
})
```

**View all skipped signals:**
```js
db.signals.find({ acted_on: false })
```

**View lifetime performance per market:**
```js
db.market_performance.find({})
```

**View last 7 daily summaries:**
```js
db.daily_summary.find({}).sort({ date: -1 }).limit(7)
```

**Count winning vs losing trades per market:**
```js
db.trades.aggregate([
  { $match: { status: "CLOSED" } },
  { $group: {
    _id: { symbol: "$symbol", result: { $cond: [{ $gt: ["$pnl", 0] }, "WIN", "LOSS"] } },
    count: { $sum: 1 }
  }}
])
```

---

## MongoDB Compass Setup

1. Download MongoDB Compass: https://www.mongodb.com/products/compass
2. Connect to: `mongodb://localhost:27017`
3. Select database: `unified_bot`
4. Browse all 5 collections visually

---

## Backup Command

Run this to backup the entire database:
```bash
mongodump --db unified_bot --out ./backups/
```

Restore:
```bash
mongorestore --db unified_bot ./backups/unified_bot/
```
