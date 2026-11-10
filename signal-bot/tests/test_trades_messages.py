import unittest

from signal_bot import trades
from signal_bot.exchanges import Candle
from signal_bot.indicators import StrategyConfig, levels_at
from signal_bot.leverage import Leverage, est_liquidation, parse_leverage, roe_pct, stop_beyond_liquidation
from signal_bot.messages import event_message, fmt_price, pair_label, signal_message


def candle(ts, high, low):
    return Candle(ts, 100, high, low, 100, 1)


def long_trade():
    return trades.open_trade(levels_at(100.0, 1, 2.0, StrategyConfig()), entry_ts=10)


class TradeTests(unittest.TestCase):
    def test_entry_bar_is_ignored(self):
        self.assertEqual(trades.advance(long_trade(), candle(10, 200, 0), StrategyConfig()), [])

    def test_targets_hit_in_order_and_close_on_tp3(self):
        t = long_trade()
        self.assertEqual(trades.advance(t, candle(11, 103, 99), StrategyConfig()), ["tp1"])
        ev = trades.advance(t, candle(12, 107, 100), StrategyConfig())
        self.assertEqual(ev, ["tp2", "tp3"])
        self.assertTrue(trades.is_finished(ev))

    def test_stop_wins_when_both_touched(self):
        ev = trades.advance(long_trade(), candle(11, 105, 96), StrategyConfig())
        self.assertEqual(ev, ["sl"])

    def test_short_trade(self):
        t = trades.open_trade(levels_at(100.0, -1, 2.0, StrategyConfig()), entry_ts=10)
        self.assertEqual(trades.advance(t, candle(11, 101, 97.5), StrategyConfig()), ["tp1"])
        self.assertEqual(trades.advance(t, candle(12, 103.5, 99), StrategyConfig()), ["sl"])

    def test_break_even_after_tp1(self):
        cfg = StrategyConfig(be_after_tp1=True)
        t = long_trade()
        trades.advance(t, candle(11, 103, 99), cfg)
        self.assertEqual(trades.advance(t, candle(12, 101, 99.5), cfg), ["sl"])  # stop is now the entry
        t2 = long_trade()
        trades.advance(t2, candle(11, 103, 99), StrategyConfig())
        self.assertEqual(trades.advance(t2, candle(12, 101, 99.5), StrategyConfig()), [])  # not enabled


class MessageTests(unittest.TestCase):
    def test_fmt_price(self):
        self.assertEqual(fmt_price(65000.123), "65000.12")
        self.assertEqual(fmt_price(1.5), "1.5")
        self.assertEqual(fmt_price(100.0), "100")
        self.assertEqual(fmt_price(0.00001234), "0.00001234")

    def test_pair_label(self):
        self.assertEqual(pair_label("ARBUSDT"), "ARB/USDT")
        self.assertEqual(pair_label("ARB-USDT"), "ARB/USDT")
        self.assertEqual(pair_label("1000SHIBUSDT"), "1000SHIB/USDT")
        self.assertEqual(pair_label("btcfdusd"), "BTC/FDUSD")
        self.assertEqual(pair_label("ETHBUSD"), "ETH/BUSD")
        self.assertEqual(pair_label("USDCUSDT"), "USDC/USDT")
        self.assertEqual(pair_label("eth/usdc"), "ETH/USDC")
        self.assertEqual(pair_label("WEIRD"), "WEIRD")

    def test_signal_message_matches_the_channel_format_exactly(self):
        short = trades.open_trade(levels_at(0.16189, -1, 0.0012, StrategyConfig()), entry_ts=10)
        text = signal_message("ARBUSDT", "15m", "Binance Futures", short, Leverage(10, "cross", 0.5))
        self.assertEqual(text, "\n".join([
            "#ARB/USDT",
            "SHORT",
            "Entry Targets:",
            "1) 0.16189",
            "Take-Profit Targets:",
            "1) 0.16069",
            "2) 0.15949",
            "3) 0.15829",
            "Stop Targets:",
            "1) 0.16369",
            "Leverage: Cross (10x)",
        ]))

    def test_long_signal_and_no_leverage_line_when_off(self):
        text = signal_message("BTC-USDT", "15m", "BloFin", long_trade())
        self.assertEqual(text.splitlines()[:5], ["#BTC/USDT", "LONG", "Entry Targets:", "1) 100", "Take-Profit Targets:"])
        self.assertEqual(text.splitlines()[5:], ["1) 102", "2) 104", "3) 106", "Stop Targets:", "1) 97"])
        self.assertNotIn("Leverage", text)

    def test_nothing_extra_in_the_signal(self):
        text = signal_message("ARBUSDT", "15m", "Binance Futures", long_trade(), Leverage())
        for banned in ("15m", "Binance", "ROE", "liquidation", "financial advice", "<b>", "<code>"):
            self.assertNotIn(banned, text)

    def test_symbol_is_escaped(self):
        text = signal_message("<b>X</b>", "15m", "v", long_trade())
        self.assertNotIn("<b>", text)
        self.assertIn("&lt;B&gt;X&lt;/B&gt;", text)

    def test_event_messages(self):
        t = long_trade()
        tp = event_message("BTCUSDT", "15m", "BloFin", t, "tp2")
        self.assertEqual(tp, "#BTC/USDT\n🎯 TP2 hit (long)\nTarget: 104 (+4.00%)")
        self.assertEqual(event_message("BTCUSDT", "15m", "BloFin", t, "sl"), "#BTC/USDT\n🛑 Stop hit (long)\nStop: 97 (-3.00%)")
        self.assertIn("Stop: 100 (", event_message("BTCUSDT", "15m", "BloFin", t, "sl", stop=100.0))


class LeverageTests(unittest.TestCase):
    LEV = Leverage(15, "cross", 0.5)

    def test_roe_and_liquidation(self):
        self.assertAlmostEqual(roe_pct(1, 100, 102, self.LEV), 30.0)    # +2% move x 15
        self.assertAlmostEqual(roe_pct(1, 100, 97, self.LEV), -45.0)
        self.assertAlmostEqual(roe_pct(-1, 100, 98, self.LEV), 30.0)    # short profits when price falls
        self.assertAlmostEqual(est_liquidation(1, 100, self.LEV), 100 * (1 - 1 / 15 + 0.005))
        self.assertAlmostEqual(est_liquidation(-1, 100, self.LEV), 100 * (1 + 1 / 15 - 0.005))

    def test_stop_beyond_liquidation(self):
        liq = est_liquidation(1, 100, self.LEV)            # about 93.83
        self.assertTrue(stop_beyond_liquidation(1, 93.0, liq))
        self.assertFalse(stop_beyond_liquidation(1, 97.0, liq))
        sliq = est_liquidation(-1, 100, self.LEV)
        self.assertTrue(stop_beyond_liquidation(-1, 107.0, sliq))
        self.assertFalse(stop_beyond_liquidation(-1, 103.0, sliq))

    def test_display(self):
        self.assertEqual(Leverage(15, "cross").display, "Cross (15x)")
        self.assertEqual(Leverage(10, "isolated").display, "Isolated (10x)")
        self.assertEqual(Leverage(2.5, "cross").display, "Cross (2.5x)")

    def test_signal_message_shows_leverage_line_last(self):
        text = signal_message("BTCUSDT", "15m", "BloFin", long_trade(), self.LEV)
        self.assertEqual(text.splitlines()[-1], "Leverage: Cross (15x)")

    def test_event_messages_with_leverage(self):
        self.assertIn("+30.0% ROE", event_message("X", "15m", "v", long_trade(), "tp1", lev=self.LEV))
        self.assertIn("-45.0% ROE", event_message("X", "15m", "v", long_trade(), "sl", lev=self.LEV))

    def test_parse_leverage(self):
        self.assertEqual(parse_leverage(15), Leverage(15.0, "cross", 0.5))
        self.assertEqual(parse_leverage({"x": 10, "mode": "Isolated"}).label, "10x isolated")
        self.assertIsNone(parse_leverage(None))
        self.assertIsNone(parse_leverage(0))
        for bad in (200, 0.5, {"x": 15, "mode": "weird"}, {"x": 15, "nope": 1}, {"x": 15, "maintenance_pct": 50}, "15x"):
            with self.assertRaises(ValueError, msg=str(bad)):
                parse_leverage(bad)


if __name__ == "__main__":
    unittest.main()
