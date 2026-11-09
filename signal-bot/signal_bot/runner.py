"""Poll loop: fetch closed candles, run the signal engine, post new signals and TP / stop events."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence

from . import trades
from .config import BotConfig, ConfigError, Pair, load_config
from .exchanges import TIMEFRAME_MS, Candle, ExchangeError, make_client
from .indicators import analyse, levels_at
from .messages import event_message, signal_message
from .notifier import ConsoleNotifier, NotifyError, TelegramNotifier

log = logging.getLogger("signal_bot")


# ---------------------------------------------------------------- state
def load_state(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.warning("state file %s is corrupt, starting fresh", path)
        return {}


def save_state(path: str, state: Dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- core
def process_series(
    key: str,
    symbol: str,
    timeframe: str,
    venue: str,
    candles: Sequence[Candle],
    state: Dict,
    cfg: BotConfig,
    send: Callable[[str], None],
    replay: int = 0,
) -> int:
    """Handle every closed candle newer than the last one processed. Returns the number of messages sent.

    First sight of a series records the latest candle and sends nothing, so starting the bot never
    replays old signals. `replay=N` treats the last N candles as new (for dry runs).
    """
    if len(candles) < 60:
        log.warning("%s: only %d candles, need more history", key, len(candles))
        return 0
    slot = state.setdefault(key, {})
    if "last_ts" not in slot:
        idx = max(0, len(candles) - 1 - replay)
        slot["last_ts"] = candles[idx].ts if replay else candles[-1].ts
        slot["trade"] = None
        if not replay:
            log.info("%s: tracking from %s", key, candles[-1].ts)
            return 0

    analysis = analyse(candles, cfg.strategy)
    sent = 0
    for i, candle in enumerate(candles):
        if candle.ts <= slot["last_ts"]:
            continue
        trade = slot.get("trade")
        if trade:
            events = trades.advance(trade, candle, cfg.strategy)
            for ev in events:
                stop = trade["entry"] if (ev == "sl" and cfg.strategy.be_after_tp1 and trade["hit"][0]) else None
                send(event_message(symbol, timeframe, venue, trade, ev, stop, cfg.leverage))
                sent += 1
            if trades.is_finished(events):
                slot["trade"] = None
        if analysis.buy[i] or analysis.sell[i]:
            direction = 1 if analysis.buy[i] else -1
            lv = levels_at(candle.close, direction, analysis.atr[i], cfg.strategy)
            if lv.entry == lv.entry and lv.sl == lv.sl:  # skip if ATR was not ready (NaN)
                slot["trade"] = trades.open_trade(lv, candle.ts)
                send(signal_message(symbol, timeframe, venue, slot["trade"], cfg.leverage))
                sent += 1
        slot["last_ts"] = candle.ts
    return sent


def is_due(slot: Optional[Dict], timeframe: str, now_ms: int) -> bool:
    """A new candle can only be closed once now >= last_ts + 2 * timeframe (ts is the open time)."""
    if not slot or "last_ts" not in slot:
        return True
    return now_ms >= slot["last_ts"] + 2 * TIMEFRAME_MS[timeframe]


def run_pass(cfg: BotConfig, state: Dict, send: Callable[[str], None], replay: int = 0, clients: Optional[Dict] = None,
             now_ms: Optional[int] = None, backoff: Optional[Dict] = None) -> int:
    """One sweep over every pair. A series that fails (unknown or delisted symbol, exchange outage) is
    retried after 1, 2, 4 ... minutes, up to 1 hour, instead of on every poll."""
    clients = clients if clients is not None else {}
    backoff = backoff if backoff is not None else {}
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    sent = 0
    for pair in cfg.pairs:
        ckey = (pair.exchange, pair.market)
        if ckey not in clients:
            clients[ckey] = make_client(pair.exchange, pair.market)
        client = clients[ckey]
        for tf in pair.timeframes or cfg.timeframes:
            key = f"{pair.exchange}:{pair.market or '-'}:{pair.symbol}:{tf}"
            if not replay and not is_due(state.get(key), tf, now_ms):
                continue
            if key in backoff and now_ms < backoff[key][1]:
                continue
            try:
                candles = client.candles(pair.symbol, tf, cfg.history)
                sent += process_series(key, pair.symbol, tf, client.label, candles, state, cfg, send, replay)
                backoff.pop(key, None)
            except (ExchangeError, NotifyError) as e:
                fails = backoff.get(key, (0, 0))[0] + 1
                delay = min(60 * 2 ** (fails - 1), 3600)
                backoff[key] = (fails, now_ms + delay * 1000)
                log.error("%s: %s (retrying in %ds)", key, e, delay)
    return sent


# ---------------------------------------------------------------- cli
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="signal_bot", description="Post Algo Signals from Binance / BloFin candles to Telegram")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--state", default=None, help="state file (default: state.json next to the config)")
    ap.add_argument("--once", action="store_true", help="run a single pass and exit")
    ap.add_argument("--dry-run", action="store_true", help="print messages instead of sending to Telegram")
    ap.add_argument("--replay", type=int, default=0, metavar="N", help="treat the last N closed candles as new (use with --dry-run)")
    ap.add_argument("--test-telegram", action="store_true", help="send one test message and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.test_telegram:
        try:
            TelegramNotifier.from_env().send("✅ Algo Signals bot connected")
        except NotifyError as e:
            log.error("%s", e)
            return 1
        print("test message sent")
        return 0

    try:
        cfg = load_config(args.config)
        notifier = ConsoleNotifier() if args.dry_run else TelegramNotifier.from_env()
    except (ConfigError, NotifyError) as e:
        log.error("%s", e)
        return 2

    state_path = args.state or os.path.join(os.path.dirname(os.path.abspath(args.config)), "state.json")
    state = {} if args.replay else load_state(state_path)
    clients: Dict = {}
    backoff: Dict = {}
    log.info("watching %d pair(s), every %ds%s", len(cfg.pairs), cfg.poll_seconds, " (dry run)" if args.dry_run else "")
    try:
        while True:
            run_pass(cfg, state, notifier.send, args.replay, clients, backoff=backoff)
            if not args.replay:
                save_state(state_path, state)
            if args.once or args.replay:
                return 0
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        log.info("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
