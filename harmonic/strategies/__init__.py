"""Strategy registry.

Register new strategies here (or call `register()` from your own module).
Config picks which ones are active via the `strategies` list.
"""
from __future__ import annotations

from typing import Dict, List, Type

from .base import Strategy
from .harmonic import HarmonicStrategy

_REGISTRY: Dict[str, Type[Strategy]] = {}


def register(cls: Type[Strategy]) -> Type[Strategy]:
    _REGISTRY[cls.name] = cls
    return cls


def available() -> List[str]:
    return list(_REGISTRY)


def label_of(name: str) -> str:
    cls = _REGISTRY.get(name)
    return cls.label if cls else name


def get_strategy(name: str) -> Strategy:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown strategy '{name}'. available: {available()}"
        )
    return _REGISTRY[name]()


def active_strategies(names: List[str]) -> List[Strategy]:
    return [get_strategy(n) for n in names if n in _REGISTRY]


register(HarmonicStrategy)
