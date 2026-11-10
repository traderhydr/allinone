"""Telegram message text (HTML parse mode, but plain content). Every dynamic value is escaped.

Signal layout:

    #ARB/USDT
    SHORT
    Entry Targets:
    1) 0.16189
    Take-Profit Targets:
    1) 0.16065
    2) 0.15941
    3) 0.15818
    Stop Targets:
    1) 0.16374
    Leverage: Cross (15x)
"""
from __future__ import annotations

from html import escape
from typing import Dict, Optional

from .leverage import Leverage, move_pct, roe_pct

QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "USD")  # longest-match order matters: FDUSD / BUSD before USD


def fmt_price(x: float) -> str:
    decimals = 2 if abs(x) >= 1000 else 4 if abs(x) >= 1 else 8
    s = f"{x:.{decimals}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def pair_label(symbol: str) -> str:
    """'ARBUSDT' / 'ARB-USDT' -> 'ARB/USDT'; '1000SHIBUSDT' -> '1000SHIB/USDT'."""
    s = symbol.upper().replace("-", "/").replace("_", "/")
    if "/" in s:
        return s
    for quote in QUOTES:
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return s


def _pct(x: float) -> str:
    return f"{x:+.2f}%"


def _roe(x: float) -> str:
    return f"{x:+.1f}% ROE"


def _with_lev(trade: Dict, price: float, lev: Optional[Leverage]) -> str:
    """' (+0.55% · +8.2% ROE)' with leverage, ' (+0.55%)' without."""
    d, e = trade["dir"], trade["entry"]
    if lev is None:
        return f" ({_pct(move_pct(d, e, price))})"
    return f" ({_pct(move_pct(d, e, price))} · {_roe(roe_pct(d, e, price, lev))})"


def signal_message(symbol: str, timeframe: str, venue: str, trade: Dict, lev: Optional[Leverage] = None) -> str:
    """`timeframe` and `venue` are accepted for a stable call signature but the channel format omits them."""
    lines = [
        f"#{escape(pair_label(symbol))}",
        "LONG" if trade["dir"] == 1 else "SHORT",
        "Entry Targets:",
        f"1) {fmt_price(trade['entry'])}",
        "Take-Profit Targets:",
    ]
    lines += [f"{i}) {fmt_price(tp)}" for i, tp in enumerate(trade["tps"], 1)]
    lines += ["Stop Targets:", f"1) {fmt_price(trade['sl'])}"]
    if lev:
        lines.append(f"Leverage: {escape(lev.display)}")
    return "\n".join(lines)


def event_message(symbol: str, timeframe: str, venue: str, trade: Dict, event: str, stop: float = None,
                  lev: Optional[Leverage] = None) -> str:
    side = "long" if trade["dir"] == 1 else "short"
    head = f"#{escape(pair_label(symbol))}"
    if event == "sl":
        stop = trade["sl"] if stop is None else stop
        return f"{head}\n🛑 Stop hit ({side})\nStop: {fmt_price(stop)}{_with_lev(trade, stop, lev)}"
    n = int(event[2])
    target = trade["tps"][n - 1]
    return f"{head}\n🎯 TP{n} hit ({side})\nTarget: {fmt_price(target)}{_with_lev(trade, target, lev)}"
