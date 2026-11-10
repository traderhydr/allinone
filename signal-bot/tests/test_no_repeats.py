import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from signal_bot import runner
from signal_bot.indicators import Analysis  # noqa: F401
from signal_bot.config import parse_config
from signal_bot.notifier import NotifyError
from tests.helpers import flat
from tests.test_runner_notifier import fake_analyse_factory, series

CFG = parse_config({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "timeframes": ["15m"], "follow_ups": True})
KEY = "k"


def run(candles, state, send, buy_at=(), sell_at=(), cfg=CFG, save=None):
    with mock.patch.object(runner, "analyse", fake_analyse_factory(set(buy_at), set(sell_at))):
        return runner.process_series(KEY, "BTC-USDT", "15m", "Binance Futures", candles, state, cfg, send, 0, save)


def started():
    state = {}
    run(flat(100), state, lambda m: None)  # first sight: records the latest candle, sends nothing
    return state


class FlakySender:
    """Delivers messages, but raises NotifyError on the call numbers listed in `fail_on` (1-based)."""

    def __init__(self, fail_on=()):
        self.fail_on, self.calls, self.delivered = set(fail_on), 0, []

    def __call__(self, text):
        self.calls += 1
        if self.calls in self.fail_on:
            raise NotifyError("telegram down")
        self.delivered.append(text)


class SameDirectionTests(unittest.TestCase):
    def test_second_buy_while_long_is_open_is_ignored(self):
        state, out = started(), []
        run(series([(100.5, 99.5), (100.5, 99.5), (100.5, 99.5)]), state, out.append, buy_at={100, 102})
        self.assertEqual(sum("LONG" in m for m in out), 1)
        self.assertEqual(state[KEY]["trade"]["entry_ts"], series([(0, 0)] * 1)[100].ts)  # still the first trade

    def test_same_direction_is_allowed_again_once_the_trade_closed(self):
        state, out = started(), []
        # BUY, stop-out candle, BUY again -> two trades are legitimate
        run(series([(100.5, 99.5), (101, 96), (100.5, 99.5)]), state, out.append, buy_at={100, 102})
        self.assertEqual(sum("LONG" in m for m in out), 2)

    def test_opposite_signal_still_reverses(self):
        state, out = started(), []
        run(series([(100.5, 99.5), (100.5, 99.5)]), state, out.append, buy_at={100}, sell_at={101})
        self.assertEqual([("LONG" in m, "SHORT" in m) for m in out], [(True, False), (False, True)])

    def test_cooldown_blocks_signals_right_after_the_previous_one(self):
        cfg = parse_config({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}], "cooldown_bars": 3})
        state, out = started(), []
        # BUY at 100, opposite SELL at 101 (inside cooldown, ignored), SELL at 104 (3 bars later, allowed)
        run(series([(100.5, 99.5)] * 5), state, out.append, buy_at={100}, sell_at={101, 104}, cfg=cfg)
        self.assertEqual([("LONG" in m, "SHORT" in m) for m in out], [(True, False), (False, True)])

    def test_cooldown_validation(self):
        from signal_bot.config import ConfigError
        with self.assertRaises(ConfigError):
            parse_config({"pairs": [{"exchange": "binance", "symbol": "X"}], "cooldown_bars": -1})


class FollowUpSwitchTests(unittest.TestCase):
    OFF = parse_config({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}]})  # follow_ups defaults to off

    def test_only_the_signal_is_posted_when_follow_ups_are_off(self):
        state, out = started(), []
        run(series([(100.5, 99.5), (102.5, 99), (104.5, 100), (106.5, 100)]), state, out.append, buy_at={100}, cfg=self.OFF)
        self.assertEqual(len(out), 1)
        self.assertIn("LONG", out[0])
        self.assertIsNone(state[KEY]["trade"])          # the bot still followed the trade to TP3

    def test_repeat_protection_still_works_when_follow_ups_are_off(self):
        state, out = started(), []
        run(series([(100.5, 99.5), (100.5, 99.5), (100.5, 99.5)]), state, out.append, buy_at={100, 102}, cfg=self.OFF)
        self.assertEqual(len(out), 1)                    # second BUY ignored: the first trade is still open
        out2 = []
        run(series([(100.5, 99.5), (101, 96), (100.5, 99.5)]), started(), out2.append, buy_at={100, 102}, cfg=self.OFF)
        self.assertEqual(len(out2), 2)                   # stopped out in between, so a new BUY is a new trade


class LiquidationLogTests(unittest.TestCase):
    def test_stop_beyond_liquidation_is_logged_but_not_added_to_the_message(self):
        def wide_atr(candles, c):                      # ATR 5 on price 100: stop 7.5 away, liquidation about 6.2 away
            n = len(candles)
            return Analysis([i == 100 for i in range(n)], [False] * n, [5.0] * n)
        state, out = started(), []
        with mock.patch.object(runner, "analyse", wide_atr), self.assertLogs("signal_bot", "WARNING") as logs:
            runner.process_series(KEY, "BTCUSDT", "15m", "v", series([(100.5, 99.5)]), state, CFG, out.append)
        self.assertIn("beyond the estimated liquidation", logs.output[0])
        self.assertNotIn("liquidation", out[0])


class DeliveryTests(unittest.TestCase):
    def test_failed_send_is_kept_and_delivered_exactly_once_later(self):
        state = started()
        candles = series([(100.5, 99.5), (102.5, 99), (104.5, 100)])  # BUY, TP1, TP2
        sender = FlakySender(fail_on={2})                               # BUY ok, TP1 fails
        with self.assertRaises(NotifyError):
            run(candles, state, sender, buy_at={100})
        self.assertEqual(len(sender.delivered), 1)
        self.assertEqual(len(state[KEY]["outbox"]), 2)                  # TP1 and TP2 still queued, in order

        # next pass: nothing new on the exchange, the queue is flushed first
        cfg_pairs = parse_config({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}]})
        key = "binance:-:BTC-USDT:15m"
        state[key] = state.pop(KEY)
        client = mock.Mock(label="Binance Futures", candles=mock.Mock(return_value=candles))
        with mock.patch.object(runner, "analyse", fake_analyse_factory({100})):
            runner.run_pass(cfg_pairs, state, sender, clients={("binance", None): client}, now_ms=0, backoff={})
        texts = sender.delivered
        self.assertEqual([("LONG" in m, "TP1 hit" in m, "TP2 hit" in m) for m in texts],
                         [(True, False, False), (False, True, False), (False, False, True)])
        self.assertEqual(state[key]["outbox"], [])
        with mock.patch.object(runner, "analyse", fake_analyse_factory({100})):
            runner.run_pass(cfg_pairs, state, sender, clients={("binance", None): client}, now_ms=10**12, backoff={})
        self.assertEqual(len(sender.delivered), 3)                      # nothing is sent a second time

    def test_state_is_saved_before_anything_is_sent_and_after_each_delivery(self):
        state, snapshots = started(), []
        sender = FlakySender()

        def save():
            snapshots.append(copy.deepcopy(state[KEY]))
        run(series([(100.5, 99.5), (102.5, 99)]), state, sender, buy_at={100}, save=save)
        # first save happens before delivery: it already holds both messages and the advanced last_ts
        self.assertEqual(len(snapshots[0]["outbox"]), 2)
        self.assertEqual(snapshots[0]["last_ts"], series([(0, 0)] * 2)[101].ts)
        self.assertEqual([len(x["outbox"]) for x in snapshots], [2, 1, 0])

    def test_restart_after_a_crash_resumes_the_outbox_without_duplicates(self):
        state, delivered = started(), []

        def dying_send(text):
            if len(delivered) == 1:
                raise KeyboardInterrupt           # process killed while the 2nd message is being sent
            delivered.append(text)

        persisted = {}

        def save():
            persisted["state"] = json.dumps(state)
        with self.assertRaises(KeyboardInterrupt):
            run(series([(100.5, 99.5), (102.5, 99)]), state, dying_send, buy_at={100}, save=save)

        restarted = json.loads(persisted["state"])                       # what state.json held at the crash
        self.assertEqual(len(restarted[KEY]["outbox"]), 1)
        runner.flush_outbox(restarted[KEY], delivered.append)
        self.assertEqual(len(delivered), 2)                              # BUY once, TP1 once
        self.assertEqual(sum("LONG" in m for m in delivered), 1)

    def test_nothing_is_lost_when_telegram_fails_on_a_stop_message(self):
        state = started()
        sender = FlakySender(fail_on={2})
        with self.assertRaises(NotifyError):
            run(series([(100.5, 99.5), (101, 96)]), state, sender, buy_at={100})      # BUY ok, stop fails
        self.assertIsNone(state[KEY]["trade"])                           # trade is closed in state...
        self.assertEqual(len(state[KEY]["outbox"]), 1)                   # ...and its message is still queued
        runner.flush_outbox(state[KEY], sender)
        self.assertIn("Stop hit", sender.delivered[-1])


class LockTests(unittest.TestCase):
    @unittest.skipIf(runner.fcntl is None, "needs fcntl")
    def test_second_instance_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json.lock")
            first = runner.acquire_lock(path)
            self.assertIsNotNone(first)
            self.assertIsNone(runner.acquire_lock(path))
            first.close()
            again = runner.acquire_lock(path)
            self.assertIsNotNone(again)
            again.close()

    @unittest.skipIf(runner.fcntl is None, "needs fcntl")
    def test_main_exits_with_3_when_already_running(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "config.json")
            json.dump({"pairs": [{"exchange": "binance", "symbol": "BTC-USDT"}]}, open(cfg_path, "w"))
            holder = runner.acquire_lock(os.path.join(d, "state.json.lock"))
            with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}):
                self.assertEqual(runner.main(["--config", cfg_path, "--once"]), 3)
                # a dry run does not need the lock, so it may run next to the service
                with mock.patch.object(runner, "run_pass", return_value=0):
                    self.assertEqual(runner.main(["--config", cfg_path, "--once", "--dry-run"]), 0)
            holder.close()


if __name__ == "__main__":
    unittest.main()
