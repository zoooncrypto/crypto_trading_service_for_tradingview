"""Harmonic pattern ratio tables and the XABCD matcher.

Each pattern is defined by Fibonacci ranges on a set of named ratios:

  AB_XA  = |AB| / |XA|        (B retracement of the XA leg)
  BC_AB  = |BC| / |AB|        (C retracement of the AB leg)
  CD_BC  = |CD| / |BC|        (D extension of the BC leg)
  AD_XA  = |AD| / |XA|        (D retracement/extension of the XA leg)
  BC_XA  = |BC| / |XA|        (Cypher: C measured against XA)
  CD_XC  = |CD| / |XC|        (Cypher: D as a retracement of XC)

A window of 5 strictly-alternating pivots is a valid pattern if its
geometry is the right shape (X/A/B/C/D alternate the right way) and every
required ratio falls inside its tolerance-expanded range.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models import Direction, PatternMatch, Pivot

Range = Tuple[float, float]


@dataclass(frozen=True)
class PatternSpec:
    name: str
    rules: Dict[str, Range]
    # nominal values used only for the quality score (tightness of fit)
    nominal: Dict[str, float]


# Ranges follow Scott Carney's harmonic definitions. They are intentionally
# data, not code, so they can be tuned without touching the matcher.
PATTERNS: List[PatternSpec] = [
    PatternSpec(
        "Gartley",
        {"AB_XA": (0.618, 0.618), "BC_AB": (0.382, 0.886),
         "CD_BC": (1.13, 1.618), "AD_XA": (0.786, 0.786)},
        {"AB_XA": 0.618, "AD_XA": 0.786},
    ),
    PatternSpec(
        "Bat",
        {"AB_XA": (0.382, 0.500), "BC_AB": (0.382, 0.886),
         "CD_BC": (1.618, 2.618), "AD_XA": (0.886, 0.886)},
        {"AB_XA": 0.45, "AD_XA": 0.886},
    ),
    PatternSpec(
        "Butterfly",
        {"AB_XA": (0.786, 0.786), "BC_AB": (0.382, 0.886),
         "CD_BC": (1.618, 2.618), "AD_XA": (1.272, 1.618)},
        {"AB_XA": 0.786, "AD_XA": 1.27},
    ),
    PatternSpec(
        "Crab",
        {"AB_XA": (0.382, 0.618), "BC_AB": (0.382, 0.886),
         "CD_BC": (2.618, 3.618), "AD_XA": (1.618, 1.618)},
        {"AB_XA": 0.5, "AD_XA": 1.618},
    ),
    PatternSpec(
        "DeepCrab",
        {"AB_XA": (0.886, 0.886), "BC_AB": (0.382, 0.886),
         "CD_BC": (2.0, 3.618), "AD_XA": (1.618, 1.618)},
        {"AB_XA": 0.886, "AD_XA": 1.618},
    ),
    PatternSpec(
        "Shark",
        {"AB_XA": (0.382, 0.618), "BC_AB": (1.13, 1.618),
         "CD_BC": (1.27, 2.24), "AD_XA": (0.886, 1.13)},
        {"BC_AB": 1.27, "AD_XA": 1.0},
    ),
    PatternSpec(
        "Cypher",
        {"AB_XA": (0.382, 0.618), "BC_XA": (1.272, 1.414),
         "CD_XC": (0.786, 0.786)},
        {"BC_XA": 1.34, "CD_XC": 0.786},
    ),
]


def _ratios(x: float, a: float, b: float, c: float, d: float) -> Dict[str, float]:
    xa = abs(a - x)
    ab = abs(b - a)
    bc = abs(c - b)
    cd = abs(d - c)
    ad = abs(d - a)
    xc = abs(c - x)
    out: Dict[str, float] = {}
    if xa:
        out["AB_XA"] = ab / xa
        out["AD_XA"] = ad / xa
        out["BC_XA"] = bc / xa
    if ab:
        out["BC_AB"] = bc / ab
    if bc:
        out["CD_BC"] = cd / bc
    if xc:
        out["CD_XC"] = cd / xc
    return out


def _in_range(value: float, lo: float, hi: float, tol: float) -> bool:
    return lo * (1.0 - tol) <= value <= hi * (1.0 + tol)


def _quality(ratios: Dict[str, float], spec: PatternSpec) -> float:
    """1.0 = ratios sit exactly on nominal values, decaying with distance."""
    if not spec.nominal:
        return 0.5
    errs = []
    for key, target in spec.nominal.items():
        if key in ratios and target:
            errs.append(abs(ratios[key] - target) / target)
    if not errs:
        return 0.5
    return max(0.0, 1.0 - sum(errs) / len(errs))


def _valid_shape(x: Pivot, a: Pivot, b: Pivot, c: Pivot, d: Pivot,
                 direction: Direction) -> bool:
    px, pa, pb, pc, pd = x.price, a.price, b.price, c.price, d.price
    if direction is Direction.LONG:
        # bullish: X low, A high, B low, C high, D low; D should sit below B.
        return px < pa and pb < pa and pb > px and pc > pb and pd < pc and pd < pb
    # bearish: X high, A low, B high, C low, D high; D should sit above B.
    return px > pa and pb > pa and pb < px and pc < pb and pd > pc and pd > pb


def _prz(spec: PatternSpec, x: float, a: float, direction: Direction) -> Tuple[float, float]:
    """Project the AD_XA range from A along the XA leg to get the PRZ zone."""
    rule = spec.rules.get("AD_XA")
    xa = abs(a - x)
    if rule is None or xa == 0:
        return (0.0, 0.0)
    lo_r, hi_r = rule
    if direction is Direction.LONG:
        # D is below A by lo_r..hi_r of XA
        p1 = a - lo_r * xa
        p2 = a - hi_r * xa
    else:
        p1 = a + lo_r * xa
        p2 = a + hi_r * xa
    return (min(p1, p2), max(p1, p2))


def match_window(pivots: List[Pivot], tol: float = 0.05,
                  min_quality: float = 0.0) -> Optional[PatternMatch]:
    """Try to match the last 5 pivots against every pattern; best fit wins."""
    if len(pivots) < 5:
        return None
    x, a, b, c, d = pivots[-5:]
    direction = Direction.LONG if not x.is_high else Direction.SHORT

    best: Optional[PatternMatch] = None
    for spec in PATTERNS:
        if not _valid_shape(x, a, b, c, d, direction):
            continue
        ratios = _ratios(x.price, a.price, b.price, c.price, d.price)
        ok = True
        for key, (lo, hi) in spec.rules.items():
            v = ratios.get(key)
            if v is None or not _in_range(v, lo, hi, tol):
                ok = False
                break
        if not ok:
            continue
        q = _quality(ratios, spec)
        if q < min_quality:
            continue
        if best is None or q > best.quality:
            prz_lo, prz_hi = _prz(spec, x.price, a.price, direction)
            best = PatternMatch(
                name=spec.name, direction=direction,
                x=x, a=a, b=b, c=c, d=d, ratios=ratios,
                prz_low=prz_lo, prz_high=prz_hi, quality=q,
            )
    return best


def detect(pivots: List[Pivot], tol: float = 0.05,
           min_quality: float = 0.0) -> List[PatternMatch]:
    """Scan every 5-pivot window across the series."""
    out: List[PatternMatch] = []
    for end in range(5, len(pivots) + 1):
        m = match_window(pivots[end - 5:end], tol, min_quality)
        if m is not None:
            out.append(m)
    return out
