import math
import unittest

from signal_bot import indicators as ind
from signal_bot.indicators import StrategyConfig
from tests.helpers import flat, random_walk


class IndicatorTests(unittest.TestCase):
    def test_ema_seeds_with_first_value(self):
        self.assertEqual(ind.ema([1, 2, 3], 3), [1, 1.5, 2.25])

    def test_rma_seeds_with_sma(self):
        out = ind.rma([1, 2, 3, 4], 2)
        self.assertTrue(math.isnan(out[0]))
        self.assertEqual(out[1:], [1.5, 2.25, 3.125])

    def test_atr_of_constant_range(self):
        h, l, c = [11.0] * 30, [9.0] * 30, [10.0] * 30
        out = ind.atr(h, l, c, 14)
        self.assertTrue(math.isnan(out[12]))
        self.assertAlmostEqual(out[13], 2.0)
        self.assertAlmostEqual(out[-1], 2.0)

    def test_supertrend_matches_hand_calculation(self):
        # worked through the Pine code by hand, factor 1:
        # bar0 -> upper band forced to 0 (nz of missing previous band), direction 1
        # bar1 -> upper 15, direction 1; bar2 -> close 16 > upper 15, direction -1, line = lower band 12
        h, l, c = [11, 12, 17], [9, 10, 15], [10, 11, 16]
        st, d = ind.infinity_supertrend(h, l, c, 1.0)
        self.assertEqual(st, [0.0, 15, 12])
        self.assertEqual(d, [1, 1, -1])
        self.assertTrue(ind.crossover(c, st, 2))
        self.assertFalse(ind.crossunder(c, st, 2))

    def test_mcginley_constant(self):
        out = ind.mcginley([5.0] * 50, 7)
        self.assertTrue(all(abs(x - 5.0) < 1e-9 for x in out))

    def test_levels_long_short_atr(self):
        cfg = StrategyConfig()
        lv = ind.levels_at(100.0, 1, 2.0, cfg)
        self.assertEqual((lv.sl, lv.tps), (97.0, (102.0, 104.0, 106.0)))
        sv = ind.levels_at(100.0, -1, 2.0, cfg)
        self.assertEqual((sv.sl, sv.tps), (103.0, (98.0, 96.0, 94.0)))

    def test_levels_percent(self):
        cfg = StrategyConfig(level_mode="Percent")
        lv = ind.levels_at(100.0, 1, 2.0, cfg)
        self.assertEqual((lv.sl, lv.tps), (96.0, (101.0, 103.0, 105.0)))

    def test_signals_are_exclusive_and_only_on_crosses(self):
        candles = random_walk(500)
        cfg = StrategyConfig(sensitivity=0.5, braid=False)
        a = ind.analyse(candles, cfg)
        self.assertEqual(len(a.buy), 500)
        self.assertFalse(any(b and s for b, s in zip(a.buy, a.sell)))
        self.assertGreater(sum(a.buy) + sum(a.sell), 0)
        st, _ = ind.infinity_supertrend([c.high for c in candles], [c.low for c in candles], [c.close for c in candles], 0.5)
        for i, c in enumerate(candles):
            if a.buy[i]:
                self.assertGreater(c.close, st[i])
            if a.sell[i]:
                self.assertLess(c.close, st[i])

    def test_braid_filter_never_adds_signals(self):
        candles = random_walk(500)
        loose = ind.analyse(candles, StrategyConfig(sensitivity=0.5, braid=False))
        strict = ind.analyse(candles, StrategyConfig(sensitivity=0.5, braid=True))
        self.assertLessEqual(sum(strict.buy), sum(loose.buy))
        self.assertLessEqual(sum(strict.sell), sum(loose.sell))
        for i in range(500):
            if strict.buy[i]:
                self.assertTrue(loose.buy[i])

    def test_flat_market_gives_no_signals(self):
        a = ind.analyse(flat(200), StrategyConfig())
        self.assertFalse(any(a.buy) or any(a.sell))


if __name__ == "__main__":
    unittest.main()
