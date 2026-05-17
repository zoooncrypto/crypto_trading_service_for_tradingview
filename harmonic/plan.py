"""Turn a detected pattern into a concrete trade plan (entry/SL/TP1-3)."""
from __future__ import annotations

from .config import Config
from .models import Direction, PatternMatch, Signal, SignalStatus


def build_signal(m: PatternMatch, symbol: str, timeframe: str,
                 cfg: Config) -> Signal:
    entry = (m.prz_low + m.prz_high) / 2.0
    xa = abs(m.a.price - m.x.price)
    buffer = xa * cfg.sl_buffer_pct / 100.0

    if m.direction is Direction.LONG:
        stop = m.x.price - buffer
    else:
        stop = m.x.price + buffer

    risk = abs(entry - stop) or 1e-9

    if cfg.tp_mode == "cd_fib":
        # Retrace the CD leg back toward C: 0.382 / 0.618 / 1.0 (=C).
        cd = abs(m.d.price - m.c.price)
        sign = 1.0 if m.direction is Direction.LONG else -1.0
        tp1 = entry + sign * 0.382 * cd
        tp2 = entry + sign * 0.618 * cd
        tp3 = entry + sign * 1.000 * cd
    else:
        r1, r2, r3 = (cfg.tp_r_multiples + [1, 2, 3])[:3]
        sign = 1.0 if m.direction is Direction.LONG else -1.0
        tp1 = entry + sign * r1 * risk
        tp2 = entry + sign * r2 * risk
        tp3 = entry + sign * r3 * risk

    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        pattern=m.name,
        direction=m.direction,
        created_ms=m.d.timestamp,
        x_price=m.x.price,
        a_price=m.a.price,
        c_price=m.c.price,
        d_price=m.d.price,
        prz_low=m.prz_low,
        prz_high=m.prz_high,
        entry=entry,
        stop=stop,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        quality=round(m.quality, 4),
        r_unit=round(risk, 10),
        status=SignalStatus.PENDING,
    )
