"""Configuration loading (config.harmonic.ini / .json)."""
from __future__ import annotations

import configparser
import json
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # exchange / account
    exchange: str = "bybit"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    mode: str = "paper"           # paper | live
    market_type: str = "swap"     # swap (USDT perp) | spot

    # universe / scan
    quote: str = "USDT"
    timeframes: List[str] = field(default_factory=lambda: ["1h", "4h"])
    max_symbols: int = 30         # top-N by volume; 0 = all
    symbols: List[str] = field(default_factory=list)  # explicit override
    ohlcv_limit: int = 300
    scan_interval_sec: int = 300

    # detection
    zigzag_depth: int = 5
    zigzag_deviation_pct: float = 0.5
    ratio_tolerance: float = 0.06
    min_quality: float = 0.4

    # trade plan
    risk_per_trade: float = 1.0   # units of "amount" sizing
    amount: float = 0.0           # base/contract size per trade (0 = use risk model)
    sl_buffer_pct: float = 0.5    # extra room beyond X, % of XA
    tp_mode: str = "rmultiple"    # rmultiple | cd_fib
    tp_r_multiples: List[float] = field(default_factory=lambda: [1.0, 2.0, 3.0])
    tp_partials: List[float] = field(default_factory=lambda: [0.4, 0.3, 0.3])

    # pending -> market conversion
    pending_max_bars: int = 8     # cancel/convert if unfilled this many bars
    convert_to_market: bool = True
    prz_breach_pct: float = 0.3   # if price runs past PRZ by this %, market in

    # service
    db_path: str = "harmonic.db"
    web_host: str = "0.0.0.0"
    web_port: int = 8800
    log_level: str = "INFO"


def _coerce(cfg: Config, section: dict):
    for key, raw in section.items():
        if not hasattr(cfg, key):
            continue
        cur = getattr(cfg, key)
        if isinstance(cur, bool):
            setattr(cfg, key, str(raw).strip().lower() in ("1", "true", "yes", "on"))
        elif isinstance(cur, int) and not isinstance(cur, bool):
            setattr(cfg, key, int(float(raw)))
        elif isinstance(cur, float):
            setattr(cfg, key, float(raw))
        elif isinstance(cur, list):
            if isinstance(raw, list):
                vals = raw
            else:
                vals = [s.strip() for s in str(raw).split(",") if s.strip()]
            if cur and isinstance(cur[0], float):
                vals = [float(v) for v in vals]
            setattr(cfg, key, vals)
        else:
            setattr(cfg, key, str(raw))


def load_config(path: str | None = None) -> Config:
    cfg = Config()
    candidates = [path] if path else [
        "config.harmonic.json", "config.harmonic.ini",
    ]
    for cand in candidates:
        if not cand or not os.path.exists(cand):
            continue
        if cand.endswith(".json"):
            data = json.load(open(cand, encoding="utf-8"))
            flat = {}
            for v in data.values():
                if isinstance(v, dict):
                    flat.update(v)
            flat.update({k: v for k, v in data.items() if not isinstance(v, dict)})
            _coerce(cfg, flat)
        else:
            parser = configparser.ConfigParser()
            parser.read(cand, encoding="utf-8")
            for sec in parser.sections():
                _coerce(cfg, dict(parser[sec]))
        break

    # Environment overrides for secrets (never commit keys).
    cfg.api_key = os.getenv("BYBIT_API_KEY", cfg.api_key)
    cfg.api_secret = os.getenv("BYBIT_API_SECRET", cfg.api_secret)
    return cfg
