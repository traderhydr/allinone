"""Python port of the Algo Signals engine (algo-signals.pine): Infinity Algo signals,
McGinley Braid filter and UT Bot-style ATR trade levels.

Moving averages follow Pine's seeding so the numbers line up with TradingView:
ta.ema starts from the first value, ta.rma / ta.atr start from an SMA of the first `length` values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .exchanges import Candle

NAN = float("nan")


def isnan(x: float) -> bool:
    return x != x


@dataclass(frozen=True)
class StrategyConfig:
    sensitivity: float = 6.0
    braid: bool = True
    braid_strength: float = 60.0
    level_mode: str = "ATR"  # "ATR" or "Percent"
    atr_len: int = 14
    tp_atr: Tuple[float, float, float] = (1.0, 2.0, 3.0)
    sl_atr: float = 1.5
    tp_pct: Tuple[float, float, float] = (1.0, 3.0, 5.0)
    sl_pct: float = 4.0
    be_after_tp1: bool = False


def ema(values: Sequence[float], n: int) -> List[float]:
    alpha = 2.0 / (n + 1)
    out: List[float] = []
    for i, v in enumerate(values):
        out.append(v if i == 0 else alpha * v + (1 - alpha) * out[-1])
    return out


def rma(values: Sequence[float], n: int) -> List[float]:
    out = [NAN] * len(values)
    if len(values) < n:
        return out
    out[n - 1] = sum(values[:n]) / n
    for i in range(n, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return out


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], n: int) -> List[float]:
    tr = [high[0] - low[0]]
    for i in range(1, len(close)):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return rma(tr, n)


def infinity_supertrend(high, low, close, factor: float):
    """Range supertrend from Infinity Algo: band half-width = factor * 2 * (high - low).

    Mirrors the Pine code bar for bar, including its first-bar behaviour (nz() of a missing
    previous band is 0). Returns (supertrend, direction) where direction -1 is up, 1 is down.
    """
    n = len(close)
    st = [NAN] * n
    direction = [0] * n
    lower = [NAN] * n
    upper = [NAN] * n
    for i in range(n):
        rangec = 2 * (high[i] - low[i])
        up = close[i] + factor * rangec
        lo = close[i] - factor * rangec
        prev_lo = lower[i - 1] if i > 0 else 0.0
        prev_up = upper[i - 1] if i > 0 else 0.0
        prev_close = close[i - 1] if i > 0 else NAN
        lo = lo if (lo > prev_lo or prev_close < prev_lo) else prev_lo
        up = up if (up < prev_up or prev_close > prev_up) else prev_up
        lower[i], upper[i] = lo, up
        if i == 0:
            d = 1
        elif st[i - 1] == prev_up:
            d = -1 if close[i] > up else 1
        else:
            d = 1 if close[i] < lo else -1
        direction[i] = d
        st[i] = lo if d == -1 else up
    return st, direction


def mcginley(src: Sequence[float], n: int) -> List[float]:
    e = ema(src, n)
    mg = [0.0] * len(src)
    for i in range(len(src)):
        if i == 0 or mg[i - 1] == 0:
            mg[i] = e[i]
        else:
            prev = mg[i - 1]
            mg[i] = prev + (src[i] - prev) / (n * (src[i] / prev) ** 4)
    return mg


def crossover(a: Sequence[float], b: Sequence[float], i: int) -> bool:
    return i > 0 and a[i] > b[i] and a[i - 1] <= b[i - 1]


def crossunder(a: Sequence[float], b: Sequence[float], i: int) -> bool:
    return i > 0 and a[i] < b[i] and a[i - 1] >= b[i - 1]


@dataclass
class Analysis:
    buy: List[bool]
    sell: List[bool]
    atr: List[float]


def analyse(candles: Sequence[Candle], cfg: StrategyConfig) -> Analysis:
    o = [c.open for c in candles]
    h = [c.high for c in candles]
    l = [c.low for c in candles]
    c_ = [c.close for c in candles]
    n = len(c_)

    st, _ = infinity_supertrend(h, l, c_, cfg.sensitivity)
    ma01, ma02, ma03 = mcginley(c_, 3), mcginley(o, 7), mcginley(c_, 20)
    atr14 = atr(h, l, c_, 14)
    atr_levels = atr(h, l, c_, cfg.atr_len)

    buy = [False] * n
    sell = [False] * n
    for i in range(n):
        dif = max(ma01[i], ma02[i], ma03[i]) - min(ma01[i], ma02[i], ma03[i])
        braid_min = atr14[i] * cfg.braid_strength / 100
        braid_up = ma01[i] > ma02[i] and dif > braid_min
        braid_dn = ma02[i] > ma01[i] and dif > braid_min
        buy[i] = crossover(c_, st, i) and (not cfg.braid or braid_up)
        sell[i] = crossunder(c_, st, i) and (not cfg.braid or braid_dn)
    return Analysis(buy, sell, atr_levels)


@dataclass
class Levels:
    direction: int  # 1 long, -1 short
    entry: float
    sl: float
    tps: Tuple[float, float, float]


def levels_at(entry: float, direction: int, atr_value: float, cfg: StrategyConfig) -> Levels:
    if cfg.level_mode.upper() == "ATR":
        dist_tp = tuple(atr_value * m for m in cfg.tp_atr)
        dist_sl = atr_value * cfg.sl_atr
    else:
        dist_tp = tuple(entry * p / 100 for p in cfg.tp_pct)
        dist_sl = entry * cfg.sl_pct / 100
    tps = tuple(entry + direction * d for d in dist_tp)
    return Levels(direction, entry, entry - direction * dist_sl, tps)  # type: ignore[arg-type]
