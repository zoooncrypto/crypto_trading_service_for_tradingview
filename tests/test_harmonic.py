"""Unit tests for the harmonic engine (no network / no exchange)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harmonic.config import Config
from harmonic.models import Direction, Pivot, Signal, SignalStatus
from harmonic.patterns import match_window
from harmonic.plan import build_signal
from harmonic.state_machine import advance
from harmonic.zigzag import find_pivots


def piv(i, price, is_high):
    return Pivot(index=i, timestamp=i * 1000, price=price, is_high=is_high)


class TestPatterns(unittest.TestCase):
    def test_bullish_gartley(self):
        # X=100 low, A=200 high, AB=0.618 XA, BC=0.5 AB, AD=0.786 XA
        x = piv(0, 100.0, False)
        a = piv(1, 200.0, True)
        b = piv(2, 200.0 - 0.618 * 100, False)   # 138.2
        c = piv(3, b.price + 0.5 * (a.price - b.price), True)  # 169.1
        d = piv(4, 200.0 - 0.786 * 100, False)   # 121.4
        m = match_window([x, a, b, c, d], tol=0.06, min_quality=0.3)
        self.assertIsNotNone(m)
        self.assertEqual(m.name, "Gartley")
        self.assertEqual(m.direction, Direction.LONG)
        self.assertGreater(m.quality, 0.8)

    def test_no_match_random_shape(self):
        pts = [piv(0, 100, False), piv(1, 101, True), piv(2, 99, False),
               piv(3, 102, True), piv(4, 50, False)]
        self.assertIsNone(match_window(pts, tol=0.02, min_quality=0.9))


class TestZigZag(unittest.TestCase):
    def test_alternating_pivots(self):
        prices = [10, 11, 12, 11, 10, 9, 10, 11, 12, 13, 12, 11,
                  10, 9, 8, 9, 10, 11, 12, 13]
        ohlcv = [[i * 1000, p, p + 0.5, p - 0.5, p, 1] for i, p in enumerate(prices)]
        pivots = find_pivots(ohlcv, depth=2, deviation_pct=0.0)
        self.assertGreaterEqual(len(pivots), 3)
        for prev, nxt in zip(pivots, pivots[1:]):
            self.assertNotEqual(prev.is_high, nxt.is_high)


class TestStateMachine(unittest.TestCase):
    def _sig(self):
        return Signal(
            symbol="BTC/USDT:USDT", timeframe="4h", pattern="Gartley",
            direction=Direction.LONG, created_ms=0,
            x_price=90, a_price=200, c_price=169, d_price=100,
            prz_low=99, prz_high=101, entry=100, stop=90,
            tp1=110, tp2=120, tp3=130, quality=0.9, r_unit=10,
        )

    def _cfg(self):
        c = Config()
        c.tp_partials = [0.4, 0.3, 0.3]
        c.convert_to_market = True
        return c

    def test_full_winner(self):
        s, cfg = self._sig(), self._cfg()
        advance(s, [1000, 100, 101, 99, 100, 1], 1, cfg)
        self.assertEqual(s.status, SignalStatus.RUNNING)
        advance(s, [2000, 100, 110, 100, 108, 1], 2, cfg)
        self.assertEqual(s.status, SignalStatus.TP1)
        self.assertAlmostEqual(s.stop, 100.0)  # breakeven
        advance(s, [3000, 108, 120, 108, 118, 1], 3, cfg)
        self.assertEqual(s.status, SignalStatus.TP2)
        self.assertAlmostEqual(s.stop, 110.0)  # locked at TP1
        advance(s, [4000, 118, 130, 118, 128, 1], 4, cfg)
        self.assertEqual(s.status, SignalStatus.TP3)
        # 0.4*1R + 0.3*2R + 0.3*3R = 1.9R
        self.assertAlmostEqual(s.realized_r, 1.9, places=3)

    def test_stop_loss_before_tp(self):
        s, cfg = self._sig(), self._cfg()
        advance(s, [1000, 100, 101, 99, 100, 1], 1, cfg)
        advance(s, [2000, 100, 101, 89, 90, 1], 2, cfg)
        self.assertEqual(s.status, SignalStatus.STOPPED)
        self.assertAlmostEqual(s.realized_r, -1.0, places=3)

    def test_pending_market_conversion_on_gap(self):
        s, cfg = self._sig(), self._cfg()
        # Opens below PRZ (but above stop) -> limit would miss -> convert.
        evs = advance(s, [1000, 95, 96, 93, 94, 1], 1, cfg)
        self.assertIn("entry_market_converted", evs)
        self.assertTrue(s.converted_to_market)
        self.assertEqual(s.status, SignalStatus.RUNNING)

    def test_pending_expiry_without_convert(self):
        s, cfg = self._sig(), self._cfg()
        cfg.convert_to_market = False
        cfg.pending_max_bars = 2
        advance(s, [1000, 150, 151, 149, 150, 1], 1, cfg)  # away from PRZ
        advance(s, [2000, 150, 151, 149, 150, 1], 2, cfg)
        self.assertEqual(s.status, SignalStatus.EXPIRED)

    def test_protective_stop_keeps_win_label(self):
        s, cfg = self._sig(), self._cfg()
        advance(s, [1000, 100, 101, 99, 100, 1], 1, cfg)
        advance(s, [2000, 100, 110, 100, 108, 1], 2, cfg)  # TP1, stop->100
        evs = advance(s, [3000, 105, 106, 99, 100, 1], 3, cfg)  # back to stop
        self.assertIn("protective_stop", evs)
        self.assertEqual(s.status, SignalStatus.TP1)  # still a win
        self.assertAlmostEqual(s.realized_r, 0.4, places=3)


class TestPlan(unittest.TestCase):
    def test_rmultiple_plan(self):
        x = piv(0, 100.0, False)
        a = piv(1, 200.0, True)
        b = piv(2, 138.2, False)
        c = piv(3, 169.1, True)
        d = piv(4, 121.4, False)
        m = match_window([x, a, b, c, d], tol=0.06, min_quality=0.3)
        cfg = Config()
        sig = build_signal(m, "ETH/USDT:USDT", "1h", cfg)
        self.assertEqual(sig.direction, Direction.LONG)
        self.assertLess(sig.stop, sig.entry)         # long: stop below entry
        self.assertLess(sig.entry, sig.tp1)
        self.assertLess(sig.tp1, sig.tp2)
        self.assertLess(sig.tp2, sig.tp3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
