"""Telegram message text (HTML parse mode). Every dynamic value is escaped."""
from __future__ import annotations

from html import escape
from typing import Dict, Optional

from .leverage import Leverage, est_liquidation, move_pct, roe_pct, stop_beyond_liquidation


def fmt_price(x: float) -> str:
    decimals = 2 if abs(x) >= 1000 else 4 if abs(x) >= 1 else 8
    s = f"{x:.{decimals}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _head(symbol: str, timeframe: str, venue: str) -> str:
    return f"{escape(symbol)} · {escape(timeframe)} · {escape(venue)}"


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
    long_ = trade["dir"] == 1
    lines = [f"{'🟢 <b>BUY</b>' if long_ else '🔴 <b>SELL</b>'} · {_head(symbol, timeframe, venue)}"]
    if lev:
        lines.append(f"Leverage: <b>{escape(lev.label)}</b>")
    lines += [
        "",
        f"Entry: <code>{fmt_price(trade['entry'])}</code>",
        f"Stop: <code>{fmt_price(trade['sl'])}</code>{_with_lev(trade, trade['sl'], lev)}",
    ]
    for i, tp in enumerate(trade["tps"], 1):
        lines.append(f"TP{i}: <code>{fmt_price(tp)}</code>{_with_lev(trade, tp, lev)}")
    if lev:
        liq = est_liquidation(trade["dir"], trade["entry"], lev)
        lines += ["", f"Est. liquidation: <code>{fmt_price(liq)}</code> <i>(rough; cross margin depends on your whole account)</i>"]
        if stop_beyond_liquidation(trade["dir"], trade["sl"], liq):
            lines.append("⚠️ <b>The stop is beyond the estimated liquidation price</b>")
    lines += ["", "<i>Algo Signals · not financial advice</i>"]
    return "\n".join(lines)


def event_message(symbol: str, timeframe: str, venue: str, trade: Dict, event: str, stop: float = None,
                  lev: Optional[Leverage] = None) -> str:
    side = "long" if trade["dir"] == 1 else "short"
    head = _head(symbol, timeframe, venue)
    if event == "sl":
        stop = trade["sl"] if stop is None else stop
        return f"🛑 <b>Stop hit</b> · {head} ({side})\nStop: <code>{fmt_price(stop)}</code>{_with_lev(trade, stop, lev)}"
    n = int(event[2])
    target = trade["tps"][n - 1]
    return f"🎯 <b>TP{n} hit</b> · {head} ({side})\nTarget: <code>{fmt_price(target)}</code>{_with_lev(trade, target, lev)}"
