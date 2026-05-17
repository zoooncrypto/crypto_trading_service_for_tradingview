"""Core data structures and enums shared across the package."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class SignalStatus(str, Enum):
    PENDING = "pending"      # PRZ reached, limit order resting, not yet filled
    RUNNING = "running"      # entered, no TP hit yet
    TP1 = "tp1"              # TP1 hit (partial close, SL -> breakeven)
    TP2 = "tp2"              # TP2 hit (partial close, SL -> TP1)
    TP3 = "tp3"              # TP3 hit -> fully closed (full win)
    STOPPED = "stopped"      # SL hit after entry (loss)
    EXPIRED = "expired"      # pending too long / price ran away, never entered
    CANCELLED = "cancelled"  # manually or rule cancelled before entry


# Statuses that count as "closed and resolved" for statistics.
CLOSED_STATUSES = {
    SignalStatus.TP1,
    SignalStatus.TP2,
    SignalStatus.TP3,
    SignalStatus.STOPPED,
    SignalStatus.EXPIRED,
    SignalStatus.CANCELLED,
}


@dataclass
class Pivot:
    """A ZigZag swing point."""
    index: int
    timestamp: int  # ms
    price: float
    is_high: bool


@dataclass
class PatternMatch:
    """A detected harmonic pattern (raw geometry, pre-trade-plan)."""
    name: str
    direction: Direction
    x: Pivot
    a: Pivot
    b: Pivot
    c: Pivot
    d: Pivot
    ratios: dict = field(default_factory=dict)
    prz_low: float = 0.0
    prz_high: float = 0.0
    quality: float = 0.0  # 0..1, how tightly ratios fit nominal values


@dataclass
class Signal:
    """A tradeable harmonic signal with its full TP/SL plan and state."""
    symbol: str
    timeframe: str
    pattern: str
    direction: Direction
    created_ms: int

    # geometry / plan
    x_price: float
    a_price: float
    c_price: float
    d_price: float
    prz_low: float
    prz_high: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    quality: float
    r_unit: float = 0.0  # |entry-stop| at creation; fixed R denominator

    status: SignalStatus = SignalStatus.PENDING
    entry_filled: float = 0.0      # filled entry price (0 = unfilled)
    realized_r: float = 0.0        # cumulative realized R
    closed_ms: Optional[int] = None
    id: Optional[int] = None

    # exchange linkage
    entry_order_id: Optional[str] = None
    converted_to_market: bool = False

    def to_row(self) -> dict:
        d = asdict(self)
        d["direction"] = self.direction.value
        d["status"] = self.status.value
        return d

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)
