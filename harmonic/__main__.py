"""CLI entrypoint.

  python -m harmonic scan          # continuous scan loop
  python -m harmonic scan-once     # single pass
  python -m harmonic web           # dashboard only
  python -m harmonic backtest BTC/USDT:USDT 4h 1000
"""
from __future__ import annotations

import logging
import sys

from .config import load_config


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cmd = argv[0] if argv else "scan"

    if cmd == "web":
        from .web import create_app
        create_app(cfg).run(host=cfg.web_host, port=cfg.web_port)
        return 0

    if cmd == "scan-once":
        from .scanner import Scanner
        print(Scanner(cfg).scan_once())
        return 0

    if cmd == "scan":
        import threading
        from .scanner import Scanner
        from .web import create_app
        sc = Scanner(cfg)
        threading.Thread(
            target=lambda: create_app(cfg).run(
                host=cfg.web_host, port=cfg.web_port, use_reloader=False
            ),
            daemon=True,
        ).start()
        sc.run()
        return 0

    if cmd == "backtest":
        from .backtest import backtest
        from .data import fetch_ohlcv, make_exchange
        symbol = argv[1] if len(argv) > 1 else "BTC/USDT:USDT"
        tf = argv[2] if len(argv) > 2 else "4h"
        limit = int(argv[3]) if len(argv) > 3 else 1000
        ex = make_exchange(cfg)
        ohlcv = fetch_ohlcv(ex, symbol, tf, limit)
        import json
        print(json.dumps(backtest(symbol, tf, ohlcv, cfg), indent=2))
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
