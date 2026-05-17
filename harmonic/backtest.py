"""Offline backtest: detect on history, replay the state machine, report.

Walks the OHLCV forward, runs the selected strategy at each step, and
lets the same state machine that runs live resolve every signal — so
backtest stats are produced by exactly the code path that trades.
"""
from __future__ import annotations

from typing import List

from .config import Config
from .models import SignalStatus
from .state_machine import advance
from .stats import summarize
from .strategies import get_strategy


def backtest(symbol: str, tf: str, ohlcv: List[list], cfg: Config,
             strategy_name: str = "harmonic") -> dict:
    strat = get_strategy(strategy_name)
    signals = []
    seen_keys = set()
    warm = cfg.zigzag_depth * 2 + 10

    for end in range(warm, len(ohlcv)):
        window = ohlcv[: end + 1]
        for sig in strat.detect(symbol, tf, window, cfg):
            key = (sig.strategy, sig.pattern, sig.created_ms)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            signals.append(sig)

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

    out = summarize(signals)
    out["strategy"] = strategy_name
    return out
