from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from yahooquery import Ticker


class NoDataError(Exception):
    pass


class YahooYahooQueryClient:
    def __init__(self):
        self._ticker_cache: Dict[str, Ticker] = {}

    def _get_ticker(self, symbol: str) -> Ticker:
        sym = str(symbol or "").strip().upper()
        ticker = self._ticker_cache.get(sym)
        if ticker is None:
            ticker = Ticker(sym)
            self._ticker_cache[sym] = ticker
        return ticker

    def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        sym = str(symbol or "").strip().upper()
        t = self._get_ticker(sym)
        p = (t.price or {}).get(sym, {})
        price = p.get("regularMarketPrice")
        currency = p.get("currency") or "USD"

        if price is None:
            hist = t.history(period="1d", interval="1d")
            if hist is None or hist.empty:
                raise NoDataError(f"No data returned for {symbol}.")
            price = float(hist["close"].iloc[-1])

        return {
            "symbol": sym,
            "price": float(price),
            "currency": currency,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_historical_candles(self, symbol: str, start: str, end: str, interval: str) -> List[Dict[str, Any]]:
        sym = str(symbol or "").strip().upper()
        t = self._get_ticker(sym)
        hist = t.history(start=start, end=end, interval=interval)
        if hist is None or hist.empty:
            raise NoDataError(f"No data returned for {symbol} in requested range.")

        if "symbol" in hist.index.names:
            hist = hist.xs(sym, level="symbol")

        candles: List[Dict[str, Any]] = []
        for idx, row in hist.iterrows():
            candles.append(
                {
                    "ts": int(idx.timestamp() * 1000),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0.0) or 0.0),
                }
            )
        return candles
