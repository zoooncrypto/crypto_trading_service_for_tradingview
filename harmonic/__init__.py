"""Harmonic trading service for Bybit.

Detects harmonic patterns (Gartley, Bat, Butterfly, Crab, Deep Crab,
Shark, Cypher) on Bybit OHLCV, manages a TP1/TP2/TP3 + protective-stop
state machine with pending->market conversion, persists every signal and
exposes a statistics dashboard.
"""

__version__ = "0.1.0"
