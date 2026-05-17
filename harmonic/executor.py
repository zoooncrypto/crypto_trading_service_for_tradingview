"""Order execution. Paper mode logs intent; live mode hits Bybit via ccxt.

The state machine decides *what* should happen (entry filled, TP1, stop,
market-convert); the executor turns those decisions into real orders. In
paper mode every method is a logged no-op so the full pipeline (scan ->
detect -> manage -> stats) can run with zero risk.
"""
from __future__ import annotations

import logging

import ccxt

from .config import Config
from .models import Direction, Signal

log = logging.getLogger(__name__)


class Executor:
    def __init__(self, cfg: Config, exchange: ccxt.Exchange | None = None):
        self.cfg = cfg
        self.ex = exchange
        self.live = cfg.mode == "live"

    def _side(self, sig: Signal, exit_: bool = False) -> str:
        long = sig.direction is Direction.LONG
        if exit_:
            return "sell" if long else "buy"
        return "buy" if long else "sell"

    def _size(self, sig: Signal) -> float:
        if self.cfg.amount > 0:
            return self.cfg.amount
        # Risk model: size so that |entry-stop| * size == risk_per_trade.
        return round(self.cfg.risk_per_trade / (sig.risk or 1e-9), 6)

    # ---- entry ----
    def place_pending(self, sig: Signal) -> None:
        size = self._size(sig)
        if not self.live:
            log.info("[paper] PENDING limit %s %s %s @ %.6f size=%s",
                     sig.symbol, sig.pattern, self._side(sig), sig.entry, size)
            return
        try:
            order = self.ex.create_order(
                sig.symbol, "limit", self._side(sig), size, sig.entry,
                params={"reduceOnly": False},
            )
            sig.entry_order_id = order.get("id")
            log.info("LIVE pending order %s placed id=%s",
                     sig.symbol, sig.entry_order_id)
        except Exception as e:  # noqa: BLE001
            log.error("place_pending failed %s: %s", sig.symbol, e)

    def convert_to_market(self, sig: Signal) -> None:
        size = self._size(sig)
        if not self.live:
            log.info("[paper] CONVERT->MARKET %s %s @ ~%.6f",
                     sig.symbol, self._side(sig), sig.entry_filled)
            return
        try:
            if sig.entry_order_id:
                try:
                    self.ex.cancel_order(sig.entry_order_id, sig.symbol)
                except Exception as e:  # noqa: BLE001
                    log.warning("cancel before convert failed: %s", e)
            self.ex.create_order(sig.symbol, "market", self._side(sig), size)
            log.info("LIVE market entry %s size=%s", sig.symbol, size)
        except Exception as e:  # noqa: BLE001
            log.error("convert_to_market failed %s: %s", sig.symbol, e)

    # ---- exits ----
    def reduce(self, sig: Signal, fraction: float, label: str) -> None:
        size = round(self._size(sig) * fraction, 6)
        if not self.live:
            log.info("[paper] %s reduce %s %.0f%% %s",
                     label, sig.symbol, fraction * 100, self._side(sig, True))
            return
        try:
            self.ex.create_order(
                sig.symbol, "market", self._side(sig, exit_=True), size,
                params={"reduceOnly": True},
            )
            log.info("LIVE %s reduce %s frac=%s", label, sig.symbol, fraction)
        except Exception as e:  # noqa: BLE001
            log.error("reduce(%s) failed %s: %s", label, sig.symbol, e)

    def cancel_pending(self, sig: Signal) -> None:
        if not self.live:
            log.info("[paper] CANCEL pending %s", sig.symbol)
            return
        if sig.entry_order_id:
            try:
                self.ex.cancel_order(sig.entry_order_id, sig.symbol)
            except Exception as e:  # noqa: BLE001
                log.warning("cancel_pending failed %s: %s", sig.symbol, e)
