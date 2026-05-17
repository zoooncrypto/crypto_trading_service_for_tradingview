"""SQLite persistence for signals."""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from .models import Direction, Signal, SignalStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, timeframe TEXT, pattern TEXT, direction TEXT,
    created_ms INTEGER,
    x_price REAL, a_price REAL, c_price REAL, d_price REAL,
    prz_low REAL, prz_high REAL,
    entry REAL, stop REAL, tp1 REAL, tp2 REAL, tp3 REAL,
    quality REAL, r_unit REAL,
    status TEXT, entry_filled REAL, realized_r REAL,
    closed_ms INTEGER,
    entry_order_id TEXT, converted_to_market INTEGER,
    UNIQUE(symbol, timeframe, pattern, created_ms)
);
CREATE INDEX IF NOT EXISTS idx_status ON signals(status);
"""

_COLS = [
    "symbol", "timeframe", "pattern", "direction", "created_ms",
    "x_price", "a_price", "c_price", "d_price", "prz_low", "prz_high",
    "entry", "stop", "tp1", "tp2", "tp3", "quality", "r_unit",
    "status", "entry_filled", "realized_r", "closed_ms",
    "entry_order_id", "converted_to_market",
]


class Storage:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    @staticmethod
    def _to_params(s: Signal) -> list:
        return [
            s.symbol, s.timeframe, s.pattern, s.direction.value, s.created_ms,
            s.x_price, s.a_price, s.c_price, s.d_price, s.prz_low, s.prz_high,
            s.entry, s.stop, s.tp1, s.tp2, s.tp3, s.quality, s.r_unit,
            s.status.value, s.entry_filled, s.realized_r, s.closed_ms,
            s.entry_order_id, 1 if s.converted_to_market else 0,
        ]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Signal:
        s = Signal(
            symbol=row["symbol"], timeframe=row["timeframe"],
            pattern=row["pattern"], direction=Direction(row["direction"]),
            created_ms=row["created_ms"],
            x_price=row["x_price"], a_price=row["a_price"],
            c_price=row["c_price"], d_price=row["d_price"],
            prz_low=row["prz_low"], prz_high=row["prz_high"],
            entry=row["entry"], stop=row["stop"],
            tp1=row["tp1"], tp2=row["tp2"], tp3=row["tp3"],
            quality=row["quality"], r_unit=row["r_unit"],
            status=SignalStatus(row["status"]),
            entry_filled=row["entry_filled"], realized_r=row["realized_r"],
            closed_ms=row["closed_ms"], id=row["id"],
            entry_order_id=row["entry_order_id"],
            converted_to_market=bool(row["converted_to_market"]),
        )
        return s

    def insert_if_new(self, s: Signal) -> Optional[int]:
        placeholders = ",".join("?" * len(_COLS))
        try:
            cur = self.conn.execute(
                f"INSERT INTO signals ({','.join(_COLS)}) VALUES ({placeholders})",
                self._to_params(s),
            )
            self.conn.commit()
            s.id = cur.lastrowid
            return s.id
        except sqlite3.IntegrityError:
            return None  # already known (same X-A-B-C-D / created_ms)

    def update(self, s: Signal) -> None:
        assignments = ",".join(f"{c}=?" for c in _COLS)
        self.conn.execute(
            f"UPDATE signals SET {assignments} WHERE id=?",
            self._to_params(s) + [s.id],
        )
        self.conn.commit()

    def open_signals(self) -> List[Signal]:
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE status IN ('pending','running','tp1','tp2')"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def all_signals(self, since_ms: int | None = None) -> List[Signal]:
        if since_ms:
            rows = self.conn.execute(
                "SELECT * FROM signals WHERE created_ms>=? ORDER BY created_ms DESC",
                (since_ms,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM signals ORDER BY created_ms DESC"
            ).fetchall()
        return [self._from_row(r) for r in rows]
