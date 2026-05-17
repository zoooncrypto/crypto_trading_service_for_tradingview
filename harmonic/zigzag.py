"""ZigZag swing-point detection.

Turns an OHLCV series into an alternating sequence of high/low pivots,
which is the input the harmonic matcher needs (X-A-B-C-D candidates are
windows of 5 consecutive alternating pivots).
"""
from __future__ import annotations

from typing import List

from .models import Pivot

# An OHLCV candle is [timestamp_ms, open, high, low, close, volume].


def find_pivots(ohlcv: List[list], depth: int = 5, deviation_pct: float = 0.0) -> List[Pivot]:
    """Detect alternating swing pivots.

    A bar is a candidate swing high if its high is the max within +/- `depth`
    bars (and likewise for swing lows). The result is forced to strictly
    alternate high/low; when two same-type pivots occur in a row the more
    extreme one wins. `deviation_pct` filters out swings whose move from the
    previous pivot is smaller than that percentage (noise filter).
    """
    n = len(ohlcv)
    if n < depth * 2 + 1:
        return []

    raw: List[Pivot] = []
    for i in range(depth, n - depth):
        ts = int(ohlcv[i][0])
        hi = ohlcv[i][2]
        lo = ohlcv[i][3]
        window = ohlcv[i - depth:i + depth + 1]
        is_high = hi >= max(c[2] for c in window)
        is_low = lo <= min(c[3] for c in window)
        # Ignore inside-bar ties that are both / neither.
        if is_high and not is_low:
            raw.append(Pivot(index=i, timestamp=ts, price=hi, is_high=True))
        elif is_low and not is_high:
            raw.append(Pivot(index=i, timestamp=ts, price=lo, is_high=False))

    if not raw:
        return []

    # Force strict alternation; keep the more extreme of consecutive same-type.
    cleaned: List[Pivot] = [raw[0]]
    for p in raw[1:]:
        last = cleaned[-1]
        if p.is_high == last.is_high:
            if (p.is_high and p.price >= last.price) or (
                not p.is_high and p.price <= last.price
            ):
                cleaned[-1] = p
        else:
            cleaned.append(p)

    if deviation_pct <= 0:
        return cleaned

    # Drop swings that did not move enough vs the prior kept pivot.
    filtered: List[Pivot] = [cleaned[0]]
    for p in cleaned[1:]:
        prev = filtered[-1]
        move = abs(p.price - prev.price) / prev.price * 100.0
        if move >= deviation_pct:
            filtered.append(p)
        elif (p.is_high and p.price >= prev.price) or (
            not p.is_high and p.price <= prev.price
        ):
            # More extreme than the (same-direction) prior: replace it.
            if p.is_high != prev.is_high:
                filtered.append(p)
            else:
                filtered[-1] = p
    return filtered
