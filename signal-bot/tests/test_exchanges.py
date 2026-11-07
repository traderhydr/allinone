import unittest
from unittest import mock

from signal_bot import exchanges
from signal_bot.exchanges import BinanceClient, BlofinClient, ExchangeError

NOW = 1_700_000_000_000


class BinanceTests(unittest.TestCase):
    def test_parses_and_drops_unclosed_candle(self):
        rows = [
            [NOW - 3_000_000, "10", "12", "9", "11", "5", NOW - 2_100_001, "0", 1, "0", "0", "0"],
            [NOW - 2_100_000, "11", "13", "10", "12", "6", NOW - 1_200_001, "0", 1, "0", "0", "0"],
            [NOW - 1_200_000, "12", "14", "11", "13", "7", NOW + 1, "0", 1, "0", "0", "0"],  # still forming
        ]
        with mock.patch.object(exchanges, "http_get_json", return_value=rows) as get:
            out = BinanceClient("futures").candles("btc-usdt", "15m", 500, now_ms=NOW)
        url = get.call_args[0][0]
        self.assertTrue(url.startswith("https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=500"))
        self.assertEqual(len(out), 2)
        self.assertEqual((out[0].open, out[0].high, out[0].low, out[0].close, out[0].volume), (10.0, 12.0, 9.0, 11.0, 5.0))
        self.assertLess(out[0].ts, out[1].ts)

    def test_spot_endpoint_and_limit_cap(self):
        with mock.patch.object(exchanges, "http_get_json", return_value=[]) as get:
            BinanceClient("spot").candles("ETHUSDT", "1h", 5000, now_ms=NOW)
        self.assertTrue(get.call_args[0][0].startswith("https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit=1000"))

    def test_error_payload(self):
        with mock.patch.object(exchanges, "http_get_json", return_value={"code": -1121, "msg": "Invalid symbol."}):
            with self.assertRaises(ExchangeError):
                BinanceClient().candles("NOPE", "15m")

    def test_bad_market_and_timeframe(self):
        with self.assertRaises(ExchangeError):
            BinanceClient("margin")
        with self.assertRaises(ExchangeError):
            BinanceClient().candles("BTCUSDT", "7m")


class BlofinTests(unittest.TestCase):
    BODY = {"code": "0", "msg": "success", "data": [
        ["1700000900000", "13", "14", "12", "13.5", "9", "9", "9", "0"],  # newest, unconfirmed
        ["1700000000000", "12", "13", "11", "12.5", "8", "8", "8", "1"],
        ["1699999100000", "11", "12", "10", "11.5", "7", "7", "7", "1"],
    ]}

    def test_parses_sorts_and_drops_unconfirmed(self):
        with mock.patch.object(exchanges, "http_get_json", return_value=self.BODY) as get:
            out = BlofinClient().candles("BTCUSDT", "1h", 300)
        url = get.call_args[0][0]
        self.assertIn("instId=BTC-USDT", url)
        self.assertIn("bar=1H", url)
        self.assertIn("limit=300", url)
        self.assertEqual([c.ts for c in out], [1699999100000, 1700000000000])
        self.assertEqual(out[1].close, 12.5)

    def test_api_error(self):
        with mock.patch.object(exchanges, "http_get_json", return_value={"code": "51001", "msg": "Instrument ID does not exist"}):
            with self.assertRaisesRegex(ExchangeError, "Instrument ID"):
                BlofinClient().candles("BTC-USDT", "15m")

    def test_symbol_mapping(self):
        self.assertEqual(BlofinClient.native_symbol("btcusdt"), "BTC-USDT")
        self.assertEqual(BlofinClient.native_symbol("eth/usdt"), "ETH-USDT")
        self.assertEqual(BlofinClient.native_symbol("SOL-USDT"), "SOL-USDT")


class FactoryTests(unittest.TestCase):
    def test_make_client(self):
        self.assertEqual(exchanges.make_client("Binance", "spot").label, "Binance Spot")
        self.assertEqual(exchanges.make_client("blofin").label, "BloFin")
        with self.assertRaises(ExchangeError):
            exchanges.make_client("kraken")


if __name__ == "__main__":
    unittest.main()
