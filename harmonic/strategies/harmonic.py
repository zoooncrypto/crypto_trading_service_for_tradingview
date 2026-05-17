"""Harmonic-pattern strategy (Gartley/Bat/Butterfly/Crab/Shark/Cypher)."""
from __future__ import annotations

from typing import List

from ..config import Config
from ..models import Signal
from ..patterns import match_window
from ..plan import build_signal
from ..zigzag import find_pivots
from .base import Strategy


class HarmonicStrategy(Strategy):
    name = "harmonic"
    label = "諧波 Harmonic"

    def detect(self, symbol: str, timeframe: str, ohlcv: List[list],
               cfg: Config) -> List[Signal]:
        pivots = find_pivots(
            ohlcv, cfg.zigzag_depth, cfg.zigzag_deviation_pct
        )
        if len(pivots) < 5:
            return []
        m = match_window(pivots, cfg.ratio_tolerance, cfg.min_quality)
        if m is None:
            return []
        # Only emit if D is recent (don't re-fire stale historical patterns).
        if m.d.index < len(ohlcv) - max(cfg.zigzag_depth * 3, 15):
            return []
        sig = build_signal(m, symbol, timeframe, cfg)
        sig.strategy = self.name
        return [sig]
