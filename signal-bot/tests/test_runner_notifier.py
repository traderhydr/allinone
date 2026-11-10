import os
import tempfile
import unittest
from unittest import mock

from signal_bot import notifier, runner
from signal_bot.config import ConfigError, parse_config
from signal_bot.exchanges import Candle
from signal_bot.indicators import Analysis
from signal_bot.notifier import NotifyError, TelegramNotifier
from tests.helpers import TF, flat

CFG = parse_config({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "timeframes": ["15m"], "follow_ups": True})


def fake_analyse_factory(buy_at, sell_at=()):
    def fake(candles, strategy_cfg):
        n = len(candles)
        return Analysis([i in buy_at for i in range(n)], [i in sell_at for i in range(n)], [2.0] * n)
    return fake


def series(extra):
    base = flat(100)
    return base + [Candle(base[-1].ts + (k + 1) * TF, 100, h, l, 100, 1) for k, (h, l) in enumerate(extra)]


class ProcessTests(unittest.TestCase):
    def run_series(self, candles, state, buy_at=(), sell_at=(), replay=0):
        out = []
        with mock.patch.object(runner, "analyse", fake_analyse_factory(set(buy_at), set(sell_at))):
            runner.process_series("k", "BTC-USDT", "15m", "Binance Futures", candles, state, CFG, out.append, replay)
        return out

    def test_cold_start_sends_nothing_then_follows_the_trade(self):
        state = {}
        self.assertEqual(self.run_series(flat(100), state, buy_at={99}), [])  # old signal is not replayed
        self.assertEqual(state["k"]["last_ts"], flat(100)[-1].ts)

        candles = series([(100.5, 99.5), (102.5, 99), (101, 96)])  # signal bar, TP1 bar, stop bar
        out = self.run_series(candles, state, buy_at={100})
        self.assertEqual(len(out), 3)
        self.assertIn("LONG", out[0])
        self.assertIn("TP1 hit", out[1])
        self.assertIn("Stop hit", out[2])
        self.assertIsNone(state["k"]["trade"])

    def test_messages_carry_the_configured_leverage(self):
        state = {}
        self.run_series(flat(100), state)
        out = self.run_series(series([(100.5, 99.5), (102.5, 99)]), state, buy_at={100})
        self.assertIn("Leverage: Cross (15x)", out[0])
        self.assertIn("ROE", out[1])

    def test_no_duplicates_on_second_pass(self):
        state = {}
        self.run_series(flat(100), state)
        candles = series([(100.5, 99.5)])
        self.assertEqual(len(self.run_series(candles, state, buy_at={100})), 1)
        self.assertEqual(self.run_series(candles, state, buy_at={100}), [])

    def test_catches_up_on_several_missed_candles_in_order(self):
        state = {}
        self.run_series(flat(100), state)
        out = self.run_series(series([(100.5, 99.5), (102.5, 99), (104.5, 100), (106.5, 100)]), state, buy_at={100})
        self.assertEqual([("LONG" in m, "TP1 hit" in m, "TP2 hit" in m, "TP3 hit" in m) for m in out],
                         [(True, False, False, False), (False, True, False, False), (False, False, True, False), (False, False, False, True)])

    def test_new_signal_replaces_open_trade_and_short_levels(self):
        state = {}
        self.run_series(flat(100), state)
        out = self.run_series(series([(100.5, 99.5), (100.5, 99.5)]), state, buy_at={100}, sell_at={101})
        self.assertEqual(len(out), 2)
        self.assertIn("SHORT", out[1])
        self.assertEqual(state["k"]["trade"]["dir"], -1)

    def test_replay_reports_recent_signals(self):
        state = {}
        out = self.run_series(series([(100.5, 99.5)] * 3), state, buy_at={101}, replay=5)
        self.assertEqual(len(out), 1)

    def test_too_little_history(self):
        self.assertEqual(self.run_series(flat(20), {}), [])

    def test_nan_atr_is_skipped(self):
        def nan_analyse(candles, c):
            n = len(candles)
            return Analysis([i == n - 1 for i in range(n)], [False] * n, [float("nan")] * n)
        state = {"k": {"last_ts": flat(100)[-1].ts, "trade": None}}
        out = []
        with mock.patch.object(runner, "analyse", nan_analyse):
            runner.process_series("k", "X", "15m", "v", series([(101, 99)]), state, CFG, out.append)
        self.assertEqual(out, [])


class PassTests(unittest.TestCase):
    class Client:
        label = "Fake"

        def __init__(self, candles):
            self.candles_data, self.calls = candles, 0

        def candles(self, symbol, tf, limit):
            self.calls += 1
            return self.candles_data

    def test_is_due(self):
        self.assertTrue(runner.is_due(None, "15m", 0))
        slot = {"last_ts": 1_000_000}
        self.assertFalse(runner.is_due(slot, "15m", 1_000_000 + 2 * TF - 1))
        self.assertTrue(runner.is_due(slot, "15m", 1_000_000 + 2 * TF))

    def test_run_pass_skips_series_that_are_not_due_and_survives_errors(self):
        client = self.Client(flat(100))
        clients = {("binance", None): client}
        state = {}
        last = flat(100)[-1].ts
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=last + TF)  # first sight: fetch
        self.assertEqual(client.calls, 1)
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=last + TF)  # not due: no fetch
        self.assertEqual(client.calls, 1)
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=last + 2 * TF)  # due
        self.assertEqual(client.calls, 2)

        from signal_bot.exchanges import ExchangeError
        boom = self.Client([])
        boom.candles = mock.Mock(side_effect=ExchangeError("down"))
        runner.run_pass(CFG, {}, lambda m: None, clients={("binance", None): boom})  # logs, does not raise

    def test_failing_series_backs_off_and_recovers(self):
        from signal_bot.exchanges import ExchangeError
        bad = self.Client([])
        bad.candles = mock.Mock(side_effect=ExchangeError("HTTP 400: Invalid symbol"))
        clients, backoff, state = {("binance", None): bad}, {}, {}
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=0, backoff=backoff)
        self.assertEqual(bad.candles.call_count, 1)
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=59_000, backoff=backoff)   # still waiting
        self.assertEqual(bad.candles.call_count, 1)
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=60_000, backoff=backoff)   # 1 min: retry
        self.assertEqual(bad.candles.call_count, 2)
        self.assertEqual(list(backoff.values())[0][0], 2)                                              # next wait doubles
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=60_000 + 119_000, backoff=backoff)
        self.assertEqual(bad.candles.call_count, 2)
        bad.candles = mock.Mock(return_value=flat(100))                                                # exchange recovers
        runner.run_pass(CFG, state, lambda m: None, clients=clients, now_ms=60_000 + 120_000, backoff=backoff)
        self.assertEqual(backoff, {})

    def test_one_bad_symbol_does_not_block_the_others(self):
        from signal_bot.exchanges import ExchangeError
        cfg = parse_config({"pairs": [{"exchange": "binance", "symbol": "DEADUSDT"}, {"exchange": "binance", "symbol": "BTCUSDT"}]})
        good = flat(100)

        class Mixed:
            label = "Fake"
            def candles(self, symbol, tf, limit):
                if symbol == "DEADUSDT":
                    raise ExchangeError("HTTP 400")
                return good
        state = {}
        runner.run_pass(cfg, state, lambda m: None, clients={("binance", None): Mixed()}, now_ms=0, backoff={})
        self.assertEqual([k for k in state], ["binance:-:BTCUSDT:15m"])

    def test_state_roundtrip_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            self.assertEqual(runner.load_state(p), {})
            runner.save_state(p, {"a": {"last_ts": 1}})
            self.assertEqual(runner.load_state(p), {"a": {"last_ts": 1}})
            open(p, "w").write("{broken")
            self.assertEqual(runner.load_state(p), {})


class ConfigTests(unittest.TestCase):
    def test_valid_and_defaults(self):
        cfg = parse_config({"pairs": [{"exchange": "BloFin", "symbol": "eth-usdt", "timeframes": ["1H"]}]})
        self.assertEqual((cfg.pairs[0].exchange, cfg.pairs[0].symbol, cfg.pairs[0].timeframes), ("blofin", "ETH-USDT", ["1h"]))
        self.assertEqual(cfg.strategy.sensitivity, 6.0)
        self.assertEqual(cfg.leverage.label, "15x cross")  # default

    def test_follow_ups_default_off_and_must_be_boolean(self):
        base = {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}]}
        self.assertFalse(parse_config(base).follow_ups)
        self.assertTrue(parse_config({**base, "follow_ups": True}).follow_ups)
        with self.assertRaises(ConfigError):
            parse_config({**base, "follow_ups": "yes"})

    def test_leverage_setting(self):
        base = {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}]}
        self.assertEqual(parse_config({**base, "leverage": {"x": 10, "mode": "isolated"}}).leverage.label, "10x isolated")
        self.assertIsNone(parse_config({**base, "leverage": None}).leverage)
        with self.assertRaises(ConfigError):
            parse_config({**base, "leverage": 500})

    def test_rejections(self):
        bad = [
            {},
            {"pairs": [{"exchange": "kraken", "symbol": "BTC-USDT"}]},
            {"pairs": [{"exchange": "binance"}]},
            {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "timeframes": ["7m"]},
            {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "strategy": {"nope": 1}},
            {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "strategy": {"tp_atr": [1, 2]}},
            {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "strategy": {"level_mode": "x"}},
            {"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "history": 10},
        ]
        for raw in bad:
            with self.assertRaises(ConfigError, msg=str(raw)):
                parse_config(raw)

    def test_example_config_is_valid(self):
        import json
        path = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
        cfg = parse_config(json.load(open(path)))
        self.assertEqual(len(cfg.pairs), 3)
        self.assertEqual(cfg.leverage.label, "15x cross")


class NotifierTests(unittest.TestCase):
    def test_requires_token_and_chat(self):
        with self.assertRaises(NotifyError):
            TelegramNotifier("", "@chan")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(NotifyError):
                TelegramNotifier.from_env()

    def test_send_payload(self):
        with mock.patch.object(notifier, "http_post_json", return_value=(200, {"ok": True})) as post:
            TelegramNotifier("123:ABC", "@chan").send("hi <b>x</b>")
        url, payload = post.call_args[0]
        self.assertEqual(url, "https://api.telegram.org/bot123:ABC/sendMessage")
        self.assertEqual((payload["chat_id"], payload["parse_mode"], payload["text"]), ("@chan", "HTML", "hi <b>x</b>"))

    def test_rate_limit_is_retried(self):
        replies = [(429, {"parameters": {"retry_after": 1}}), (200, {"ok": True})]
        with mock.patch.object(notifier, "http_post_json", side_effect=replies) as post, mock.patch.object(notifier.time, "sleep"):
            TelegramNotifier("t", "c").send("x")
        self.assertEqual(post.call_count, 2)

    def test_rejection_does_not_leak_the_token(self):
        with mock.patch.object(notifier, "http_post_json", return_value=(400, {"description": "chat not found"})):
            with self.assertRaises(NotifyError) as cm:
                TelegramNotifier("SECRET-TOKEN", "c").send("x")
        self.assertIn("chat not found", str(cm.exception))
        self.assertNotIn("SECRET-TOKEN", str(cm.exception))


class CliTests(unittest.TestCase):
    def test_dry_run_once_with_replay_prints_messages(self):
        import io
        import json
        from contextlib import redirect_stdout
        candles = series([(100.5, 99.5)] * 3)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            json.dump({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}]}, open(path, "w"))
            buf = io.StringIO()
            with mock.patch.object(runner, "analyse", fake_analyse_factory({101})), \
                    mock.patch("signal_bot.exchanges.BinanceClient.candles", return_value=candles), \
                    redirect_stdout(buf):
                rc = runner.main(["--config", path, "--dry-run", "--replay", "5"])
            self.assertEqual(rc, 0)
            self.assertIn("LONG", buf.getvalue())
            self.assertFalse(os.path.exists(os.path.join(d, "state.json")))

    def test_missing_config_exits_with_code_2(self):
        self.assertEqual(runner.main(["--config", "/nonexistent.json", "--dry-run"]), 2)


if __name__ == "__main__":
    unittest.main()
