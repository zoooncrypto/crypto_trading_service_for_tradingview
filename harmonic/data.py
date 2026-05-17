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
    if cfg.proxy:
        # ccxt (sync) forwards this dict to requests; covers http+https.
        ex.proxies = {"http": cfg.proxy, "https": cfg.proxy}
        if hasattr(ex, "httpsProxy"):
            ex.httpsProxy = cfg.proxy
        log.info("using proxy for %s calls", cfg.exchange)
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


_ALLOWLIST_HINT = (
    "出口防火牆封鎖了交易所 host (egress allowlist)。\n"
    "  這不是程式問題。請在 Claude Code on the web 環境的網路政策\n"
    "  把以下 host 加入 allowlist，或改在自己機器/VPS 執行：\n"
    "    - api.bybit.com\n"
    "    - api-testnet.bybit.com\n"
    "  文件: https://code.claude.com/docs/en/claude-code-on-the-web"
)


def _raw_probe(testnet: bool) -> str:
    """Hit the REST base directly to read why it was denied (egress proxy
    returns x-deny-reason: host_not_allowed when blocked by allowlist)."""
    import urllib.error
    import urllib.request

    host = "api-testnet.bybit.com" if testnet else "api.bybit.com"
    url = f"https://{host}/v5/market/time"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return f"reachable (HTTP {r.status})"
    except urllib.error.HTTPError as e:
        deny = e.headers.get("x-deny-reason", "")
        if deny == "host_not_allowed" or e.code == 403:
            return "blocked_by_allowlist"
        return f"http_error {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"network_error {type(e).__name__}"


def check_connection(cfg: Config) -> int:
    """Diagnose Bybit reachability: server time + a sample OHLCV pull."""
    import time as _t

    sample = cfg.symbols[0] if cfg.symbols else (
        "BTC/USDT:USDT" if cfg.market_type == "swap" else "BTC/USDT"
    )
    tf = cfg.timeframes[0] if cfg.timeframes else "1h"
    print(f"exchange={cfg.exchange} testnet={cfg.testnet} "
          f"market={cfg.market_type} proxy={'yes' if cfg.proxy else 'no'}")
    try:
        ex = make_exchange(cfg)
        t0 = _t.time()
        srv = ex.fetch_time()
        t1 = _t.time()
        candles = fetch_ohlcv(ex, sample, tf, 5)
        t2 = _t.time()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        print(f"\n[FAIL] {type(e).__name__}: {msg[:200]}")
        probe = _raw_probe(cfg.testnet)
        print(f"[diag] raw probe: {probe}")
        if probe == "blocked_by_allowlist" or "host_not_allowed" in msg \
                or "not in allowlist" in msg:
            print("\n" + _ALLOWLIST_HINT)
        elif probe.startswith("http_error 403"):
            print("\n  Bybit 回 403：可能是地區封鎖，改用海外 VPS 或設 proxy。")
        else:
            print("\n  檢查網路 / proxy 設定。" if not cfg.proxy
                  else "\n  proxy 可能無效，檢查 proxy 設定。")
        return 1

    print(f"\n[OK] server time   : {srv} (round-trip {(t1 - t0) * 1000:.0f} ms)")
    print(f"[OK] {sample} {tf} : {len(candles)} candles "
          f"({(t2 - t1) * 1000:.0f} ms)")
    if candles:
        c = candles[-1]
        print(f"     last bar     : ts={c[0]} o={c[1]} h={c[2]} "
              f"l={c[3]} c={c[4]}")
    print("\n連線正常，可執行: python -m harmonic scan-once")
    return 0
