import unittest

from signal_bot import trades
from signal_bot.exchanges import Candle
from signal_bot.indicators import StrategyConfig, levels_at
from signal_bot.messages import event_message, fmt_price, signal_message


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

    def test_signal_message_contents_and_escaping(self):
        text = signal_message("<b>X</b>", "15m", "Binance Futures", long_trade())
        self.assertIn("BUY", text)
        self.assertIn("&lt;b&gt;X&lt;/b&gt;", text)
        self.assertNotIn("<b>X</b>", text)
        for needle in ("Entry: <code>100</code>", "Stop: <code>97</code> (3.00%)", "TP1: <code>102</code>", "TP3: <code>106</code>"):
            self.assertIn(needle, text)

    def test_event_messages(self):
        t = long_trade()
        self.assertIn("TP2 hit", event_message("BTC-USDT", "15m", "BloFin", t, "tp2"))
        self.assertIn("Stop hit", event_message("BTC-USDT", "15m", "BloFin", t, "sl"))
        self.assertIn("<code>100</code>", event_message("BTC-USDT", "15m", "BloFin", t, "sl", stop=100.0))


if __name__ == "__main__":
    unittest.main()
