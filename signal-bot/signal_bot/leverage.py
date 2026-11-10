"""Leverage display maths. Nothing here talks to an exchange: the bot never sets leverage or places orders."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Leverage:
    x: float = 15.0
    mode: str = "cross"  # "cross" or "isolated" (label only; the estimate below is the same for both)
    maintenance_pct: float = 0.5  # approximate maintenance margin rate, % of position value

    @property
    def display(self) -> str:
        """Channel format: 'Cross (15x)'."""
        x = int(self.x) if float(self.x).is_integer() else self.x
        return f"{self.mode.capitalize()} ({x}x)"

    @property
    def label(self) -> str:
        x = int(self.x) if float(self.x).is_integer() else self.x
        return f"{x}x {self.mode}"


def move_pct(direction: int, entry: float, price: float) -> float:
    """Price move in the trade's favour, in percent (negative when against it)."""
    return direction * (price - entry) / entry * 100


def roe_pct(direction: int, entry: float, price: float, lev: Leverage) -> float:
    """Return on margin in percent, before fees and funding."""
    return move_pct(direction, entry, price) * lev.x


def est_liquidation(direction: int, entry: float, lev: Leverage) -> float:
    """Isolated-equivalent liquidation price: where this position alone would lose its whole margin
    less the maintenance requirement. With cross margin the real price also depends on the rest of the
    account balance and other positions, so treat this as a rough guide, not an exchange figure."""
    return entry * (1 - direction * (1 / lev.x - lev.maintenance_pct / 100))


def stop_beyond_liquidation(direction: int, stop: float, liq: float) -> bool:
    return stop <= liq if direction == 1 else stop >= liq


def parse_leverage(raw) -> Optional[Leverage]:
    """None / 0 / missing disables the display. Accepts a number, or {"x": 15, "mode": "cross", "maintenance_pct": 0.5}."""
    if raw in (None, 0, False):
        return None
    if isinstance(raw, (int, float)):
        raw = {"x": raw}
    if not isinstance(raw, dict):
        raise ValueError("leverage must be a number or an object")
    unknown = set(raw) - {"x", "mode", "maintenance_pct"}
    if unknown:
        raise ValueError(f"unknown leverage setting(s): {', '.join(sorted(unknown))}")
    x = float(raw.get("x", 15))
    mode = str(raw.get("mode", "cross")).lower()
    mm = float(raw.get("maintenance_pct", 0.5))
    if not 1 <= x <= 125:
        raise ValueError("leverage.x must be between 1 and 125")
    if mode not in ("cross", "isolated"):
        raise ValueError("leverage.mode must be 'cross' or 'isolated'")
    if not 0 <= mm < 100 / x:
        raise ValueError("leverage.maintenance_pct must be between 0 and 100 / leverage")
    return Leverage(x, mode, mm)
