"""
strategies/level_memory.py
───────────────────────────
Phase 3: Persistent market-structure memory.

Stores every swing high/low and range boundary the bot detects in SQLite.
Tracks touches, marks broken levels, expires old ones. Lets Phase 4 ask:
  - "what active levels are within X ATR of current price?"
  - "did price just break a level?"
  - "where's the nearest resistance above current price?"

Design decisions:
  - 'Broken' means price CLOSED beyond the level (not just wicked).
    Wicks are fakeouts; closes are real.
  - Touched counter = how many times price tested the level without breaking.
    More touches = stronger S/R.
  - Levels expire after 30 days inactive (prevents clutter).
  - Per-symbol + per-timeframe scope.
"""
import os, sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd

from strategies.market_structure import find_swing_points, classify_trend


DB_PATH_DEFAULT = os.path.join("data", "levels.db")
EXPIRE_DAYS_DEFAULT = 30

LVL_SWING_HIGH   = "swing_high"
LVL_SWING_LOW    = "swing_low"
LVL_RANGE_TOP    = "range_top"
LVL_RANGE_BOTTOM = "range_bottom"


@dataclass
class Level:
    id:            int
    symbol:        str
    timeframe:     str
    type:          str
    price:         float
    formed_at:     str
    touched_count: int
    broken_at:     Optional[str]
    broken_direction: Optional[str]
    active:        int


SCHEMA = """
CREATE TABLE IF NOT EXISTS levels (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    type             TEXT NOT NULL,
    price            REAL NOT NULL,
    formed_at        TEXT NOT NULL,
    touched_count    INTEGER DEFAULT 0,
    broken_at        TEXT,
    broken_direction TEXT,
    active           INTEGER DEFAULT 1,
    updated_at       TEXT NOT NULL,
    UNIQUE(symbol, timeframe, type, price, formed_at)
);
CREATE INDEX IF NOT EXISTS idx_levels_active ON levels(symbol, timeframe, active);
CREATE INDEX IF NOT EXISTS idx_levels_price ON levels(symbol, active, price);
"""


class LevelMemory:
    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    def _conn(self):
        return sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)

    def _init_schema(self):
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ── Writers ────────────────────────────────────────────────

    def update(
        self, symbol: str, timeframe: str, df: pd.DataFrame,
        swing_left: int = 5, swing_right: int = 5,
        range_band_pct: float = 2.0,
    ) -> dict:
        """
        Called every cycle with the latest dataframe for one (symbol, timeframe).

        1. Finds confirmed swings, upserts new ones as active levels.
        2. If structure is RANGE, upserts range_top / range_bottom levels.
        3. For each active level: checks if the current (last closed) bar
           closed beyond it → marks broken.
        4. For each active level: checks if the current bar touched it
           (high or low reached, but didn't close beyond) → increments touched_count.
        5. Expires levels older than EXPIRE_DAYS_DEFAULT.

        Returns a stats dict {inserted, broken, touched}.
        """
        if df.empty or len(df) < swing_left + swing_right + 2:
            return {"inserted": 0, "broken": 0, "touched": 0, "expired": 0}

        inserted = broken = touched = expired = 0
        now_iso = datetime.utcnow().isoformat()

        # 1. swings
        swings = find_swing_points(df, left=swing_left, right=swing_right)
        with self._conn() as c:
            for s in swings:
                kind = LVL_SWING_HIGH if s.kind == "HIGH" else LVL_SWING_LOW
                ts = df["time"].iloc[s.idx] if "time" in df.columns else str(s.idx)
                try:
                    c.execute(
                        "INSERT INTO levels (symbol, timeframe, type, price, formed_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (symbol, timeframe, kind, float(s.price), str(ts), now_iso),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # already have this exact swing

            # 2. range bounds
            report = classify_trend(df, left=swing_left, right=swing_right,
                                    min_swings=3, range_band_pct=range_band_pct)
            if report.range_support is not None:
                try:
                    c.execute(
                        "INSERT INTO levels (symbol, timeframe, type, price, formed_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (symbol, timeframe, LVL_RANGE_BOTTOM, float(report.range_support), now_iso, now_iso),
                    )
                    inserted += 1
                except sqlite3.IntegrityError: pass
            if report.range_resistance is not None:
                try:
                    c.execute(
                        "INSERT INTO levels (symbol, timeframe, type, price, formed_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (symbol, timeframe, LVL_RANGE_TOP, float(report.range_resistance), now_iso, now_iso),
                    )
                    inserted += 1
                except sqlite3.IntegrityError: pass

            # 3. check last closed bar for breaks + touches
            last_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else float(df["Close"].iloc[-1])
            last_high  = float(df["High"].iloc[-2])  if len(df) >= 2 else float(df["High"].iloc[-1])
            last_low   = float(df["Low"].iloc[-2])   if len(df) >= 2 else float(df["Low"].iloc[-1])

            for row in c.execute(
                "SELECT id, type, price FROM levels WHERE symbol=? AND timeframe=? AND active=1",
                (symbol, timeframe),
            ).fetchall():
                lid, ltype, lprice = row

                # Broken = close beyond the level
                if ltype in (LVL_SWING_HIGH, LVL_RANGE_TOP):
                    if last_close > lprice:
                        c.execute(
                            "UPDATE levels SET active=0, broken_at=?, broken_direction='UP', updated_at=? WHERE id=?",
                            (now_iso, now_iso, lid),
                        )
                        broken += 1
                        continue
                elif ltype in (LVL_SWING_LOW, LVL_RANGE_BOTTOM):
                    if last_close < lprice:
                        c.execute(
                            "UPDATE levels SET active=0, broken_at=?, broken_direction='DOWN', updated_at=? WHERE id=?",
                            (now_iso, now_iso, lid),
                        )
                        broken += 1
                        continue

                # Touched = wick reached the level (without closing beyond)
                touched_this = False
                if ltype in (LVL_SWING_HIGH, LVL_RANGE_TOP):
                    if last_high >= lprice: touched_this = True
                elif ltype in (LVL_SWING_LOW, LVL_RANGE_BOTTOM):
                    if last_low <= lprice: touched_this = True
                if touched_this:
                    c.execute(
                        "UPDATE levels SET touched_count=touched_count+1, updated_at=? WHERE id=?",
                        (now_iso, lid),
                    )
                    touched += 1

            # 4. expire old levels
            cutoff = (datetime.utcnow() - timedelta(days=EXPIRE_DAYS_DEFAULT)).isoformat()
            r = c.execute(
                "UPDATE levels SET active=0, updated_at=? "
                "WHERE active=1 AND updated_at < ?",
                (now_iso, cutoff),
            )
            expired = r.rowcount

        return {"inserted": inserted, "broken": broken, "touched": touched, "expired": expired}

    # ── Readers ────────────────────────────────────────────────

    def get_active(self, symbol: str, timeframe: Optional[str] = None) -> List[Level]:
        """All active levels for a symbol, optionally filtered by timeframe."""
        q = "SELECT id, symbol, timeframe, type, price, formed_at, touched_count, broken_at, broken_direction, active FROM levels WHERE symbol=? AND active=1"
        params = [symbol]
        if timeframe:
            q += " AND timeframe=?"; params.append(timeframe)
        q += " ORDER BY price"
        with self._conn() as c:
            return [Level(*row) for row in c.execute(q, params).fetchall()]

    def get_recently_broken(self, symbol: str, within_minutes: int = 60) -> List[Level]:
        """Levels broken within the last N minutes — Phase 4 breakout triggers."""
        cutoff = (datetime.utcnow() - timedelta(minutes=within_minutes)).isoformat()
        q = ("SELECT id, symbol, timeframe, type, price, formed_at, touched_count, broken_at, broken_direction, active "
             "FROM levels WHERE symbol=? AND broken_at >= ? ORDER BY broken_at DESC")
        with self._conn() as c:
            return [Level(*row) for row in c.execute(q, (symbol, cutoff)).fetchall()]

    def get_nearest(
        self, symbol: str, price: float, direction: str = "above",
        timeframe: Optional[str] = None,
    ) -> Optional[Level]:
        """Nearest active level above (direction='above') or below (direction='below') the given price."""
        op = ">" if direction == "above" else "<"
        order = "ASC" if direction == "above" else "DESC"
        q = (f"SELECT id, symbol, timeframe, type, price, formed_at, touched_count, broken_at, broken_direction, active "
             f"FROM levels WHERE symbol=? AND active=1 AND price {op} ?")
        params = [symbol, price]
        if timeframe:
            q += " AND timeframe=?"; params.append(timeframe)
        q += f" ORDER BY price {order} LIMIT 1"
        with self._conn() as c:
            row = c.execute(q, params).fetchone()
            return Level(*row) if row else None

    def stats(self, symbol: Optional[str] = None) -> dict:
        """Quick counts — active / broken / total."""
        where = "WHERE symbol=?" if symbol else ""
        params = [symbol] if symbol else []
        with self._conn() as c:
            active  = c.execute(f"SELECT COUNT(*) FROM levels {where} AND active=1" if where else "SELECT COUNT(*) FROM levels WHERE active=1", params).fetchone()[0]
            broken  = c.execute(f"SELECT COUNT(*) FROM levels {where} AND broken_at IS NOT NULL" if where else "SELECT COUNT(*) FROM levels WHERE broken_at IS NOT NULL", params).fetchone()[0]
            total   = c.execute(f"SELECT COUNT(*) FROM levels {where}" if where else "SELECT COUNT(*) FROM levels", params).fetchone()[0]
        return {"active": active, "broken": broken, "total": total}