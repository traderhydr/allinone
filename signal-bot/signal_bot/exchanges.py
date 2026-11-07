"""Public market-data clients for Binance (spot / USD-M futures) and BloFin (perpetual swaps).

Only public candle endpoints are used, so no exchange API keys are needed or accepted.
Every client returns *closed* candles only, oldest first.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import List, NamedTuple, Optional

TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

BLOFIN_BAR = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D",
}

USER_AGENT = "algo-signal-bot/0.1"


class Candle(NamedTuple):
    ts: int  # open time, milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float


class ExchangeError(RuntimeError):
    pass


def http_get_json(url: str, timeout: float = 15.0, retries: int = 3):
    """GET a URL and decode JSON, retrying transient failures. Tests replace this function."""
    last: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 451:
                raise ExchangeError("HTTP 451: this exchange blocks requests from this region/IP") from e
            if e.code in (400, 404):  # bad symbol / interval, retrying will not help
                raise ExchangeError(f"HTTP {e.code} from {url.split('?')[0]}: {e.reason}") from e
            last = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise ExchangeError(f"request failed after {retries} attempts: {last}")


def _check_tf(timeframe: str) -> None:
    if timeframe not in TIMEFRAME_MS:
        raise ExchangeError(f"unsupported timeframe {timeframe!r}; use one of {', '.join(TIMEFRAME_MS)}")


class BinanceClient:
    def __init__(self, market: str = "futures"):
        if market not in ("spot", "futures"):
            raise ExchangeError("binance market must be 'spot' or 'futures'")
        self.market = market
        if market == "futures":
            self.base, self.path, self.max_limit = "https://fapi.binance.com", "/fapi/v1/klines", 1500
        else:
            self.base, self.path, self.max_limit = "https://api.binance.com", "/api/v3/klines", 1000

    @property
    def label(self) -> str:
        return "Binance Futures" if self.market == "futures" else "Binance Spot"

    @staticmethod
    def native_symbol(symbol: str) -> str:
        return symbol.replace("-", "").replace("/", "").upper()

    def candles(self, symbol: str, timeframe: str, limit: int = 500, now_ms: Optional[int] = None) -> List[Candle]:
        _check_tf(timeframe)
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        url = (f"{self.base}{self.path}?symbol={self.native_symbol(symbol)}"
               f"&interval={timeframe}&limit={min(limit, self.max_limit)}")
        rows = http_get_json(url)
        if not isinstance(rows, list):
            raise ExchangeError(f"unexpected Binance response: {str(rows)[:120]}")
        out = []
        for r in rows:
            close_time = int(r[6])
            if close_time >= now_ms:  # still forming
                continue
            out.append(Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        return out


class BlofinClient:
    base = "https://openapi.blofin.com"
    max_limit = 1440
    label = "BloFin"

    @staticmethod
    def native_symbol(symbol: str) -> str:
        s = symbol.upper().replace("/", "-")
        if "-" in s:
            return s
        for quote in ("USDT", "USDC", "USD"):  # BTCUSDT -> BTC-USDT
            if s.endswith(quote) and len(s) > len(quote):
                return f"{s[:-len(quote)]}-{quote}"
        return s

    def candles(self, symbol: str, timeframe: str, limit: int = 500, now_ms: Optional[int] = None) -> List[Candle]:
        _check_tf(timeframe)
        url = (f"{self.base}/api/v1/market/candles?instId={self.native_symbol(symbol)}"
               f"&bar={BLOFIN_BAR[timeframe]}&limit={min(limit, self.max_limit)}")
        body = http_get_json(url)
        if not isinstance(body, dict) or str(body.get("code")) != "0":
            msg = body.get("msg") if isinstance(body, dict) else str(body)[:120]
            raise ExchangeError(f"BloFin error: {msg}")
        out = []
        for r in body.get("data", []):
            # [ts, open, high, low, close, vol, volCurrency, volCurrencyQuote, confirm]; confirm "1" = closed
            if len(r) > 8 and str(r[8]) != "1":
                continue
            out.append(Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        out.sort(key=lambda c: c.ts)  # BloFin returns newest first
        return out


def make_client(exchange: str, market: Optional[str] = None):
    exchange = exchange.lower()
    if exchange == "binance":
        return BinanceClient(market or "futures")
    if exchange == "blofin":
        return BlofinClient()
    raise ExchangeError(f"unknown exchange {exchange!r}; use 'binance' or 'blofin'")
