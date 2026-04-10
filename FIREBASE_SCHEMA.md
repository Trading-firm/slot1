# Firebase Firestore — Data Schema & Frontend Guide

This document describes every collection, document structure, and field stored by
the Unified Trading Bot. Use it to build your dashboard frontend.

---

## Project Info

| Item | Value |
|------|-------|
| Firebase Project | `highscore-9d90b` |
| Database | Firestore (Native mode) |
| Service Account | `firebase-adminsdk-fbsvc@highscore-9d90b.iam.gserviceaccount.com` |

---

## Collections Overview

| Collection | Doc ID | Purpose |
|------------|--------|---------|
| `trades` | ticket number (string) | Every trade opened and closed |
| `daily_summary` | date string `YYYY-MM-DD` | End-of-day performance snapshot |
| `bot_state` | key name (string) | Persistent bot key/value store |
| `market_performance` | symbol name (string) | Per-market win rate tracking |

---

## 1. `trades`

**Document ID:** the MT5 ticket number as a string (e.g. `"4572622674"`)

### Fields

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `ticket` | number | `4572622674` | MT5 order ticket |
| `symbol` | string | `"EURUSD"` | Market traded |
| `direction` | string | `"BUY"` or `"SELL"` | Trade direction |
| `entry_price` | number | `1.16846` | Price at entry |
| `sl` | number | `1.16620` | Stop loss price |
| `tp` | number | `1.17060` | Take profit price |
| `lot_size` | number | `0.01` | Lot size placed |
| `strategy` | string | `"trend_following"` | Strategy used |
| `timeframe` | string | `"M15"` | Chart timeframe |
| `rsi_at_entry` | number | `53.14` | RSI value at entry |
| `atr_at_entry` | number | `0.00214` | ATR value at entry |
| `ema_trend` | number | `1.16511` | EMA200 value at entry |
| `status` | string | `"OPEN"` or `"CLOSED"` | Current trade status |
| `entry_time` | timestamp | `2026-04-10T15:06:52Z` | When trade opened (UTC) |
| `exit_price` | number \| null | `1.17060` | Price at close (`null` if open) |
| `exit_reason` | string \| null | `"TP1"` | Why it closed (`null` if open) |
| `pnl` | number \| null | `2.14` | Profit/loss in USD (`null` if open) |
| `pnl_pct` | number \| null | `0.24` | PnL as % of balance (`null` if open) |
| `exit_time` | timestamp \| null | `2026-04-10T16:22:10Z` | When trade closed (`null` if open) |

### `exit_reason` values
| Value | Meaning |
|-------|---------|
| `"TP1"` | Hit take profit 1 (1R) |
| `"TP2"` | Hit take profit 2 (2R) |
| `"TP3"` | Hit take profit 3 (3R) — best outcome |
| `"SL"` | Hit stop loss |
| `"EARLY_EXIT"` | Closed early — trend reversed |
| `"UNKNOWN"` | MT5 history unavailable at close time |

### Example document
```json
{
  "ticket": 4572622674,
  "symbol": "BTCUSD",
  "direction": "BUY",
  "entry_price": 71026.296,
  "sl": 70417.957,
  "tp": 73075.979,
  "lot_size": 0.01,
  "strategy": "trend_following",
  "timeframe": "M30",
  "rsi_at_entry": 52.98,
  "atr_at_entry": 608.02,
  "ema_trend": 69910.79,
  "status": "CLOSED",
  "entry_time": "2026-04-10T14:06:58Z",
  "exit_price": 73075.979,
  "exit_reason": "TP3",
  "pnl": 20.49,
  "pnl_pct": 0.96,
  "exit_time": "2026-04-10T17:44:12Z"
}
```

### Common queries for your dashboard

```javascript
// All open trades
db.collection("trades").where("status", "==", "OPEN")

// All closed trades, newest first
db.collection("trades")
  .where("status", "==", "CLOSED")
  .orderBy("exit_time", "desc")
  .limit(50)

// Trades for a specific market
db.collection("trades")
  .where("symbol", "==", "EURUSD")
  .orderBy("entry_time", "desc")

// Today's trades
const today = new Date();
today.setHours(0, 0, 0, 0);
db.collection("trades").where("entry_time", ">=", today)

// Winning trades only
db.collection("trades")
  .where("status", "==", "CLOSED")
  .where("pnl", ">", 0)
```

---

## 2. `daily_summary`

**Document ID:** date string in `YYYY-MM-DD` format (e.g. `"2026-04-10"`)

### Fields

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `date` | string | `"2026-04-10"` | Date (matches doc ID) |
| `total_trades` | number | `8` | Closed trades today |
| `winning_trades` | number | `5` | Winning trades today |
| `losing_trades` | number | `3` | Losing trades today |
| `win_rate` | number | `62.5` | Win rate % today |
| `total_pnl` | number | `14.32` | Total profit/loss today (USD) |
| `best_trade` | number | `8.90` | Best single trade PnL today |
| `worst_trade` | number | `-2.14` | Worst single trade PnL today |
| `open_trades` | number | `3` | Trades still open at snapshot time |
| `updated_at` | timestamp | `2026-04-10T23:59:00Z` | Last updated (UTC) |

### Example document
```json
{
  "date": "2026-04-10",
  "total_trades": 8,
  "winning_trades": 5,
  "losing_trades": 3,
  "win_rate": 62.5,
  "total_pnl": 14.32,
  "best_trade": 8.90,
  "worst_trade": -2.14,
  "open_trades": 3,
  "updated_at": "2026-04-10T23:59:00Z"
}
```

### Common queries

```javascript
// Last 30 days of summaries
db.collection("daily_summary")
  .orderBy("date", "desc")
  .limit(30)

// A specific day
db.collection("daily_summary").doc("2026-04-10").get()

// Days with positive PnL only
db.collection("daily_summary").where("total_pnl", ">", 0)
```

---

## 3. `bot_state`

**Document ID:** the key name (e.g. `"last_cycle"`, `"status"`)

### Fields

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `key` | string | `"last_cycle"` | Key name (matches doc ID) |
| `value` | string | `"2026-04-10T15:06:39Z"` | Stored value (always string) |
| `updated_at` | timestamp | `2026-04-10T15:06:39Z` | Last updated (UTC) |

### Example document
```json
{
  "key": "last_cycle",
  "value": "2026-04-10T15:06:39Z",
  "updated_at": "2026-04-10T15:06:39Z"
}
```

### Common queries

```javascript
// Check when bot last ran
db.collection("bot_state").doc("last_cycle").get()
```

---

## 4. `market_performance`

**Document ID:** the market symbol (e.g. `"EURUSD"`, `"Volatility 75 Index"`)

### Fields

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `symbol` | string | `"EURUSD"` | Market symbol (matches doc ID) |
| `total_trades` | number | `42` | All-time closed trades |
| `wins` | number | `24` | All-time winning trades |
| `losses` | number | `18` | All-time losing trades |
| `total_pnl` | number | `68.42` | All-time profit/loss (USD) |
| `created_at` | timestamp | `2026-04-10T15:06:52Z` | First trade on this market |
| `updated_at` | timestamp | `2026-04-10T17:44:12Z` | Last updated |

### Derived values (calculate in frontend)
```javascript
const winRate = (doc.wins / doc.total_trades) * 100;
const avgPnl  = doc.total_pnl / doc.total_trades;
```

### Example document
```json
{
  "symbol": "EURUSD",
  "total_trades": 42,
  "wins": 24,
  "losses": 18,
  "total_pnl": 68.42,
  "created_at": "2026-04-10T15:06:52Z",
  "updated_at": "2026-04-10T17:44:12Z"
}
```

### Common queries

```javascript
// All markets sorted by total PnL
db.collection("market_performance").orderBy("total_pnl", "desc")

// A specific market
db.collection("market_performance").doc("EURUSD").get()

// All markets (5 docs — small, just get all)
db.collection("market_performance").get()
```

---

## Frontend Setup (Firebase Web SDK)

### Install
```bash
npm install firebase
```

### Initialize
```javascript
// firebase.js
import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";

const firebaseConfig = {
  projectId: "highscore-9d90b",
  // Get full config from Firebase Console:
  // Project Settings → General → Your apps → Web app
};

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);
```

### Example: Live open trades feed
```javascript
import { collection, query, where, onSnapshot } from "firebase/firestore";

const q = query(collection(db, "trades"), where("status", "==", "OPEN"));

onSnapshot(q, (snapshot) => {
  const openTrades = snapshot.docs.map(doc => doc.data());
  // update your UI here
});
```

### Example: Today's summary
```javascript
import { doc, getDoc } from "firebase/firestore";

const today = new Date().toISOString().split("T")[0]; // "2026-04-10"
const snap = await getDoc(doc(db, "daily_summary", today));
const summary = snap.exists() ? snap.data() : null;
```

---

## Dashboard Pages — Suggested Layout

| Page | Data sources |
|------|-------------|
| **Overview** | `daily_summary` (today) + `trades` open count + `market_performance` all |
| **Live Trades** | `trades` where `status == OPEN` — live listener |
| **Trade History** | `trades` where `status == CLOSED` — paginated, filterable by symbol |
| **Performance** | `market_performance` all + `daily_summary` last 30 days |
| **Charts** | `daily_summary` last 30/90 days for equity curve |

---

## Notes

- All timestamps are stored as Firestore `Timestamp` objects (UTC). Convert with `.toDate()` in JS.
- `pnl` is in **USD**.
- `win_rate` in `daily_summary` is already a percentage (e.g. `62.5` = 62.5%).
- The bot updates `daily_summary` at the end of every 60-second cycle.
- `market_performance` updates atomically every time a trade closes.
- For real-time updates on the dashboard, use Firestore `onSnapshot` listeners.