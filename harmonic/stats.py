"""Aggregate statistics (the dashboard cards)."""
from __future__ import annotations

from typing import Dict, List

from .models import Signal, SignalStatus


def summarize(signals: List[Signal]) -> dict:
    total = len(signals)
    running = sum(
        1 for s in signals
        if s.status in (SignalStatus.PENDING, SignalStatus.RUNNING)
    )
    tp1 = sum(1 for s in signals if s.status is SignalStatus.TP1)
    tp2 = sum(1 for s in signals if s.status is SignalStatus.TP2)
    tp3 = sum(1 for s in signals if s.status is SignalStatus.TP3)
    stopped = sum(1 for s in signals if s.status is SignalStatus.STOPPED)
    expired = sum(
        1 for s in signals
        if s.status in (SignalStatus.EXPIRED, SignalStatus.CANCELLED)
    )

    wins = tp1 + tp2 + tp3
    losses = stopped
    decided = wins + losses
    win_rate = (wins / decided * 100.0) if decided else 0.0
    loss_rate = (losses / decided * 100.0) if decided else 0.0
    cum_r = round(sum(s.realized_r for s in signals), 2)

    return {
        "total": total,
        "running": running,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "no_entry": expired,      # 無 T-Bar：到價未進場 / 失效
        "stopped": stopped,
        "cum_r": cum_r,
        "win_rate": round(win_rate, 1),
        "loss_rate": round(loss_rate, 1),
        "decided": decided,
    }


def summarize_by_strategy(signals: List[Signal]) -> Dict[str, dict]:
    """Same cards as summarize(), but split per strategy (independent
    win rate / TP1-3 / SL / total / cumulative R for each strategy)."""
    groups: Dict[str, List[Signal]] = {}
    for s in signals:
        groups.setdefault(s.strategy, []).append(s)
    return {name: summarize(grp) for name, grp in sorted(groups.items())}
