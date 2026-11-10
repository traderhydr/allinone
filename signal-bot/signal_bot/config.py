from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from .exchanges import TIMEFRAME_MS
from .indicators import StrategyConfig
from .leverage import Leverage, parse_leverage


class ConfigError(ValueError):
    pass


@dataclass
class Pair:
    exchange: str
    symbol: str
    market: Optional[str] = None
    timeframes: Optional[List[str]] = None


@dataclass
class BotConfig:
    pairs: List[Pair]
    timeframes: List[str] = field(default_factory=lambda: ["15m"])
    poll_seconds: int = 30
    history: int = 500
    follow_ups: bool = False  # also post 'TP hit' / 'Stop hit' messages; off by default (auto-trading bots read the channel)
    max_signal_age_bars: int = 1  # never post a signal more than this many candles old (e.g. after downtime)
    cooldown_bars: int = 0  # ignore new signals for this many candles after the previous one on the same series
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    leverage: Optional[Leverage] = field(default_factory=Leverage)  # 15x cross unless changed; null turns it off


def _tf(value: str) -> str:
    v = str(value).lower()
    if v not in TIMEFRAME_MS:
        raise ConfigError(f"unsupported timeframe {value!r}; use one of {', '.join(TIMEFRAME_MS)}")
    return v


def parse_config(raw: dict) -> BotConfig:
    if not isinstance(raw, dict) or not raw.get("pairs"):
        raise ConfigError("config needs a non-empty 'pairs' list")
    pairs = []
    for p in raw["pairs"]:
        ex = str(p.get("exchange", "")).lower()
        if ex not in ("binance", "blofin"):
            raise ConfigError(f"unknown exchange {p.get('exchange')!r}; use 'binance' or 'blofin'")
        if not p.get("symbol"):
            raise ConfigError("every pair needs a 'symbol', e.g. 'BTC-USDT'")
        tfs = [_tf(t) for t in p["timeframes"]] if p.get("timeframes") else None
        pairs.append(Pair(ex, str(p["symbol"]).upper(), p.get("market"), tfs))

    s = raw.get("strategy", {})
    unknown = set(s) - set(StrategyConfig.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"unknown strategy setting(s): {', '.join(sorted(unknown))}")
    conv = dict(s)
    for key in ("tp_atr", "tp_pct"):
        if key in conv:
            if len(conv[key]) != 3:
                raise ConfigError(f"strategy.{key} needs exactly 3 values")
            conv[key] = tuple(float(x) for x in conv[key])
    strat = StrategyConfig(**conv)
    if strat.level_mode.upper() not in ("ATR", "PERCENT"):
        raise ConfigError("strategy.level_mode must be 'ATR' or 'Percent'")

    try:
        lev = parse_leverage(raw["leverage"]) if "leverage" in raw else Leverage()
    except (ValueError, TypeError) as e:
        raise ConfigError(str(e))

    follow_ups = raw.get("follow_ups", False)
    if not isinstance(follow_ups, bool):
        raise ConfigError("follow_ups must be true or false")
    max_age = int(raw.get("max_signal_age_bars", 1))
    if max_age < 0:
        raise ConfigError("max_signal_age_bars cannot be negative")
    cooldown = int(raw.get("cooldown_bars", 0))
    if cooldown < 0:
        raise ConfigError("cooldown_bars cannot be negative")
    history = int(raw.get("history", 500))
    if history < 100:
        raise ConfigError("history must be at least 100 candles (the indicators need warm-up)")
    return BotConfig(
        pairs=pairs,
        timeframes=[_tf(t) for t in raw.get("timeframes", ["15m"])],
        poll_seconds=max(10, int(raw.get("poll_seconds", 30))),
        history=history,
        follow_ups=follow_ups,
        max_signal_age_bars=max_age,
        cooldown_bars=cooldown,
        strategy=strat,
        leverage=lev,
    )


def load_config(path: str) -> BotConfig:
    try:
        with open(path, encoding="utf-8") as f:
            return parse_config(json.load(f))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path} (copy config.example.json to config.json)")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}")
