"""Offline backtest: detect on history, replay the state machine, report.

Walks the OHLCV forward, runs detection at each step, and lets the same
state machine that runs live resolve every signal — so backtest stats are
produced by exactly the code path that trades.
"""
from __future__ import annotations

from typing import List

from .config import Config
from .models import SignalStatus
from .patterns import match_window
from .plan import build_signal
from .state_machine import advance
from .stats import summarize
from .zigzag import find_pivots


def backtest(symbol: str, tf: str, ohlcv: List[list], cfg: Config) -> dict:
    signals = []
    seen_keys = set()
    warm = cfg.zigzag_depth * 2 + 10

    for end in range(warm, len(ohlcv)):
        window = ohlcv[: end + 1]
        pivots = find_pivots(
            window, cfg.zigzag_depth, cfg.zigzag_deviation_pct
        )
        if len(pivots) < 5:
            continue
        m = match_window(pivots, cfg.ratio_tolerance, cfg.min_quality)
        if m is None or m.d.index < len(window) - cfg.zigzag_depth * 3:
            continue
        key = (m.name, m.x.timestamp, m.d.timestamp)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        signals.append(build_signal(m, symbol, tf, cfg))

    for sig in signals:
        bars = [c for c in ohlcv if int(c[0]) > sig.created_ms]
        for i, candle in enumerate(bars):
            before = sig.status
            advance(sig, candle, i + 1, cfg)
            if sig.status in (
                SignalStatus.TP3, SignalStatus.STOPPED,
                SignalStatus.EXPIRED, SignalStatus.CANCELLED,
            ) and before != sig.status:
                break

    return summarize(signals)
