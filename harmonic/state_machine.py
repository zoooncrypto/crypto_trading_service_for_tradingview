"""Signal life-cycle: pending -> (market convert) -> TP1/TP2/TP3 / stop.

`advance()` is pure: feed it a signal, the latest closed candle and how
many bars have elapsed since the signal was created, and it mutates the
signal's state and returns a list of human-readable events. The scanner
maps those events onto real exchange actions via the executor.
"""
from __future__ import annotations

from typing import List

from .config import Config
from .models import Direction, Signal, SignalStatus

# Candle = [ts, open, high, low, close, volume]


def _r(price_from: float, price_to: float, risk: float,
       direction: Direction) -> float:
    sign = 1.0 if direction is Direction.LONG else -1.0
    return sign * (price_to - price_from) / risk


def advance(sig: Signal, candle: list, bars_since_created: int,
            cfg: Config) -> List[str]:
    events: List[str] = []
    risk = sig.r_unit or sig.risk or 1e-9
    is_long = sig.direction is Direction.LONG
    o, hi, lo = candle[1], candle[2], candle[3]
    ts = int(candle[0])

    p1, p2, p3 = (cfg.tp_partials + [0.4, 0.3, 0.3])[:3]

    # ----- still waiting for entry -----
    if sig.status is SignalStatus.PENDING:
        # Invalidation: price broke beyond the stop before we ever filled.
        broke = lo <= sig.stop if is_long else hi >= sig.stop
        if broke and not _touched_prz(sig, hi, lo):
            sig.status = SignalStatus.EXPIRED
            sig.closed_ms = ts
            events.append("invalidated_before_entry")
            return events

        touched = _touched_prz(sig, hi, lo)
        gapped = (o < sig.prz_low if is_long else o > sig.prz_high)

        if touched:
            sig.entry_filled = sig.entry
            sig.status = SignalStatus.RUNNING
            events.append("entry_filled")
        elif gapped and cfg.convert_to_market:
            # Price opened past the PRZ — resting limit would miss it,
            # so convert to a market entry at the open.
            sig.entry_filled = o
            sig.converted_to_market = True
            sig.status = SignalStatus.RUNNING
            events.append("entry_market_converted")
        elif bars_since_created >= cfg.pending_max_bars:
            if cfg.convert_to_market:
                sig.entry_filled = o
                sig.converted_to_market = True
                sig.status = SignalStatus.RUNNING
                events.append("entry_market_converted_timeout")
            else:
                sig.status = SignalStatus.EXPIRED
                sig.closed_ms = ts
                events.append("pending_expired")
                return events
        else:
            return events  # keep waiting

    # ----- in a position -----
    if sig.status in (SignalStatus.RUNNING, SignalStatus.TP1, SignalStatus.TP2):
        # Targets ordered; check stop first to be conservative when both
        # the stop and a TP are inside the same candle.
        stop_hit = (lo <= sig.stop) if is_long else (hi >= sig.stop)
        if stop_hit:
            sig.realized_r += _r(sig.entry_filled, sig.stop, risk, sig.direction) * \
                _remaining_fraction(sig, p1, p2, p3)
            sig.closed_ms = ts
            if sig.status is SignalStatus.RUNNING:
                sig.status = SignalStatus.STOPPED
                events.append("stop_loss")
            else:
                events.append("protective_stop")  # keeps TP1/TP2 win label
            sig.realized_r = round(sig.realized_r, 4)
            return events

        def reached(level):
            return (hi >= level) if is_long else (lo <= level)

        if sig.status is SignalStatus.RUNNING and reached(sig.tp1):
            sig.realized_r += p1 * _r(sig.entry_filled, sig.tp1, risk, sig.direction)
            sig.stop = sig.entry_filled  # protective: move to breakeven
            sig.status = SignalStatus.TP1
            events.append("tp1")
        if sig.status is SignalStatus.TP1 and reached(sig.tp2):
            sig.realized_r += p2 * _r(sig.entry_filled, sig.tp2, risk, sig.direction)
            sig.stop = sig.tp1  # protective: lock in TP1
            sig.status = SignalStatus.TP2
            events.append("tp2")
        if sig.status is SignalStatus.TP2 and reached(sig.tp3):
            sig.realized_r += p3 * _r(sig.entry_filled, sig.tp3, risk, sig.direction)
            sig.status = SignalStatus.TP3
            sig.closed_ms = ts
            events.append("tp3")

        sig.realized_r = round(sig.realized_r, 4)
    return events


def _touched_prz(sig: Signal, hi: float, lo: float) -> bool:
    return lo <= sig.prz_high and hi >= sig.prz_low


def _remaining_fraction(sig: Signal, p1: float, p2: float, p3: float) -> float:
    if sig.status is SignalStatus.RUNNING:
        return 1.0
    if sig.status is SignalStatus.TP1:
        return 1.0 - p1
    if sig.status is SignalStatus.TP2:
        return 1.0 - p1 - p2
    return 0.0
