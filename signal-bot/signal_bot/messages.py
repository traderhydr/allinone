"""Telegram message text (HTML parse mode). Every dynamic value is escaped."""
from __future__ import annotations

from html import escape
from typing import Dict


def fmt_price(x: float) -> str:
    decimals = 2 if abs(x) >= 1000 else 4 if abs(x) >= 1 else 8
    s = f"{x:.{decimals}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _head(symbol: str, timeframe: str, venue: str) -> str:
    return f"{escape(symbol)} · {escape(timeframe)} · {escape(venue)}"


def signal_message(symbol: str, timeframe: str, venue: str, trade: Dict) -> str:
    long_ = trade["dir"] == 1
    risk = abs(trade["entry"] - trade["sl"]) / trade["entry"] * 100
    lines = [
        f"{'🟢 <b>BUY</b>' if long_ else '🔴 <b>SELL</b>'} · {_head(symbol, timeframe, venue)}",
        "",
        f"Entry: <code>{fmt_price(trade['entry'])}</code>",
        f"Stop: <code>{fmt_price(trade['sl'])}</code> ({risk:.2f}%)",
    ]
    for i, tp in enumerate(trade["tps"], 1):
        lines.append(f"TP{i}: <code>{fmt_price(tp)}</code>")
    lines += ["", "<i>Algo Signals · not financial advice</i>"]
    return "\n".join(lines)


def event_message(symbol: str, timeframe: str, venue: str, trade: Dict, event: str, stop: float = None) -> str:
    side = "long" if trade["dir"] == 1 else "short"
    head = _head(symbol, timeframe, venue)
    if event == "sl":
        stop = trade["sl"] if stop is None else stop
        return f"🛑 <b>Stop hit</b> · {head} ({side})\nStop: <code>{fmt_price(stop)}</code>"
    n = int(event[2])
    return f"🎯 <b>TP{n} hit</b> · {head} ({side})\nTarget: <code>{fmt_price(trade['tps'][n - 1])}</code>"
