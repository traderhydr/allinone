"""Trade tracking with the same rules as the Pine indicator: after the entry bar the stop is
checked first (conservative), then targets in order; TP3 or the stop closes the trade."""
from __future__ import annotations

from typing import Dict, List, Optional

from .exchanges import Candle
from .indicators import Levels, StrategyConfig


def open_trade(levels: Levels, entry_ts: int) -> Dict:
    return {
        "dir": levels.direction,
        "entry": levels.entry,
        "sl": levels.sl,
        "tps": list(levels.tps),
        "hit": [False, False, False],
        "entry_ts": entry_ts,
    }


def advance(trade: Dict, candle: Candle, cfg: StrategyConfig) -> List[str]:
    """Apply one closed candle to an open trade. Returns events: 'tp1', 'tp2', 'tp3', 'sl'.
    The caller drops the trade when 'sl' or 'tp3' is returned."""
    if candle.ts <= trade["entry_ts"]:
        return []
    d = trade["dir"]
    sl = trade["entry"] if (cfg.be_after_tp1 and trade["hit"][0]) else trade["sl"]
    stopped = candle.low <= sl if d == 1 else candle.high >= sl
    if stopped:
        return ["sl"]
    events: List[str] = []
    for k in range(3):
        if trade["hit"][k]:
            continue
        reached = candle.high >= trade["tps"][k] if d == 1 else candle.low <= trade["tps"][k]
        if reached:
            trade["hit"][k] = True
            events.append(f"tp{k + 1}")
    return events


def is_finished(events: List[str]) -> bool:
    return "sl" in events or "tp3" in events
