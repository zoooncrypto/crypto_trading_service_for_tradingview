"""Strategy abstraction.

A strategy turns one symbol's OHLCV into zero or more `Signal`s, each
already carrying its full entry/SL/TP plan. Everything downstream (the
TP1/TP2/TP3 + protective-stop state machine, persistence, statistics, the
dashboard) is strategy-agnostic, so adding a new strategy is just adding
one class and registering it — no changes to the engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..config import Config
from ..models import Signal


class Strategy(ABC):
    #: unique key used in config, storage and the dashboard switcher
    name: str = "base"
    #: human label shown in the UI
    label: str = "Base"

    @abstractmethod
    def detect(self, symbol: str, timeframe: str, ohlcv: List[list],
               cfg: Config) -> List[Signal]:
        """Return fresh signals (with strategy field set) for this bar."""
        raise NotImplementedError
