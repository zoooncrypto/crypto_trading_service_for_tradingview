"""Bybit market data via ccxt: symbol universe + OHLCV."""
from __future__ import annotations

import logging
from typing import List

import ccxt

from .config import Config

log = logging.getLogger(__name__)


def make_exchange(cfg: Config) -> ccxt.Exchange:
    klass = getattr(ccxt, cfg.exchange)
    ex = klass({
        "apiKey": cfg.api_key,
        "secret": cfg.api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": cfg.market_type},
    })
    if cfg.testnet and hasattr(ex, "set_sandbox_mode"):
        try:
            ex.set_sandbox_mode(True)
        except Exception as e:  # noqa: BLE001
            log.warning("sandbox mode unavailable: %s", e)
    return ex


def universe(ex: ccxt.Exchange, cfg: Config) -> List[str]:
    """Resolve the list of symbols to scan."""
    if cfg.symbols:
        return cfg.symbols
    markets = ex.load_markets()
    want_swap = cfg.market_type == "swap"
    picked = []
    for sym, m in markets.items():
        if m.get("quote") != cfg.quote:
            continue
        if want_swap and not m.get("swap"):
            continue
        if not want_swap and not m.get("spot"):
            continue
        if not m.get("active", True):
            continue
        picked.append(sym)

    if cfg.max_symbols and len(picked) > cfg.max_symbols:
        try:
            tickers = ex.fetch_tickers(picked)
            picked.sort(
                key=lambda s: (tickers.get(s, {}).get("quoteVolume") or 0),
                reverse=True,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ticker volume sort failed, using unsorted: %s", e)
        picked = picked[: cfg.max_symbols]
    return picked


def fetch_ohlcv(ex: ccxt.Exchange, symbol: str, timeframe: str,
                limit: int) -> List[list]:
    return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
