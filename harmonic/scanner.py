"""Orchestration: scan -> detect -> persist -> manage open signals."""
from __future__ import annotations

import logging
import time
from typing import List

from .config import Config
from .data import fetch_ohlcv, make_exchange, universe
from .executor import Executor
from .models import SignalStatus
from .state_machine import advance
from .storage import Storage
from .strategies import active_strategies

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ex = make_exchange(cfg)
        self.store = Storage(cfg.db_path)
        self.exec = Executor(cfg, self.ex)
        self.strategies = active_strategies(cfg.strategies)
        if not self.strategies:
            raise ValueError(
                f"no valid strategies in config: {cfg.strategies}"
            )
        log.info("active strategies: %s",
                 [s.name for s in self.strategies])

    # ---- detection of fresh signals ----
    def _detect_new(self, symbol: str, tf: str, ohlcv: List[list]) -> None:
        for strat in self.strategies:
            try:
                signals = strat.detect(symbol, tf, ohlcv, self.cfg)
            except Exception as e:  # noqa: BLE001
                log.warning("strategy %s detect %s %s failed: %s",
                            strat.name, symbol, tf, e)
                continue
            for sig in signals:
                sig.strategy = strat.name
                new_id = self.store.insert_if_new(sig)
                if new_id is not None:
                    log.info("NEW [%s] %s %s %s %s q=%.2f "
                             "entry=%.6f stop=%.6f",
                             strat.name, symbol, tf, sig.pattern,
                             sig.direction.value, sig.quality,
                             sig.entry, sig.stop)
                    self.exec.place_pending(sig)

    # ---- manage already-open signals ----
    def _manage(self, sig, ohlcv: List[list]) -> None:
        prev_status = sig.status
        bars = [c for c in ohlcv if int(c[0]) > sig.created_ms]
        for i, candle in enumerate(bars):
            before = sig.status
            events = advance(sig, candle, i + 1, self.cfg)
            for ev in events:
                self._apply(sig, ev)
            if sig.status in (
                SignalStatus.TP3, SignalStatus.STOPPED,
                SignalStatus.EXPIRED, SignalStatus.CANCELLED,
            ) and before != sig.status:
                break
        if sig.status is not prev_status or sig.realized_r:
            self.store.update(sig)

    def _apply(self, sig, event: str) -> None:
        p1, p2, p3 = (self.cfg.tp_partials + [0.4, 0.3, 0.3])[:3]
        if event in ("entry_market_converted",
                     "entry_market_converted_timeout"):
            self.exec.convert_to_market(sig)
        elif event == "entry_filled":
            log.info("ENTRY filled %s @ %.6f", sig.symbol, sig.entry_filled)
        elif event == "tp1":
            self.exec.reduce(sig, p1, "TP1")
        elif event == "tp2":
            self.exec.reduce(sig, p2, "TP2")
        elif event == "tp3":
            self.exec.reduce(sig, p3, "TP3")
        elif event in ("stop_loss", "protective_stop"):
            self.exec.reduce(sig, 1.0, "STOP")
        elif event in ("pending_expired", "invalidated_before_entry"):
            self.exec.cancel_pending(sig)

    def scan_once(self) -> dict:
        syms = universe(self.ex, self.cfg)
        log.info("scanning %d symbols x %d timeframes",
                 len(syms), len(self.cfg.timeframes))
        seen = 0
        for sym in syms:
            for tf in self.cfg.timeframes:
                try:
                    ohlcv = fetch_ohlcv(self.ex, sym, tf, self.cfg.ohlcv_limit)
                except Exception as e:  # noqa: BLE001
                    log.warning("fetch %s %s failed: %s", sym, tf, e)
                    continue
                if len(ohlcv) < 30:
                    continue
                self._detect_new(sym, tf, ohlcv)
                seen += 1
        # Manage every open signal against fresh data.
        for sig in self.store.open_signals():
            try:
                ohlcv = fetch_ohlcv(
                    self.ex, sig.symbol, sig.timeframe, self.cfg.ohlcv_limit
                )
                self._manage(sig, ohlcv)
            except Exception as e:  # noqa: BLE001
                log.warning("manage %s failed: %s", sig.symbol, e)
        return {"scanned": seen}

    def run(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception as e:  # noqa: BLE001
                log.error("scan loop error: %s", e)
            time.sleep(self.cfg.scan_interval_sec)
