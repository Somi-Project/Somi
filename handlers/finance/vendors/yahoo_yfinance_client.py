from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import yfinance as yf


class NoDataError(Exception):
    pass


class YahooYFinanceClient:
    def __init__(self):
        self._ticker_cache: Dict[str, yf.Ticker] = {}

    def _get_ticker(self, symbol: str) -> yf.Ticker:
        sym = str(symbol or "").strip().upper()
        ticker = self._ticker_cache.get(sym)
        if ticker is None:
            ticker = yf.Ticker(sym)
            self._ticker_cache[sym] = ticker
        return ticker

    def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        t = self._get_ticker(symbol)
        price = None
        currency = "USD"

        try:
            fi = getattr(t, "fast_info", None) or {}
            price = fi.get("lastPrice")
            currency = fi.get("currency") or currency
        except Exception:
            pass

        if price is None:
            data = yf.download(symbol, period="1d", interval="1m", progress=False)
            if data is None or data.empty:
                raise NoDataError(f"No data returned for {symbol}.")
            price = float(data["Close"].iloc[-1])

        return {
            "symbol": symbol,
            "price": float(price),
            "currency": currency,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_historical_candles(self, symbol: str, start: str, end: str, interval: str) -> List[Dict[str, Any]]:
        data = yf.download(symbol, start=start, end=end, interval=interval, progress=False)
        if data is None or data.empty:
            raise NoDataError(f"No data returned for {symbol} in requested range.")

        candles: List[Dict[str, Any]] = []
        for idx, row in data.iterrows():
            candles.append(
                {
                    "ts": int(idx.timestamp() * 1000),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row.get("Volume", 0.0) or 0.0),
                }
            )
        return candles
