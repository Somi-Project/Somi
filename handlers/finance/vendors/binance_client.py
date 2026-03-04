from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import requests


class UnsupportedSymbolError(Exception):
    pass


class NoDataError(Exception):
    pass


class BinanceClient:
    BASE_URL = "https://api.binance.com"

    def __init__(self, timeout_s: float = 8.0):
        self.timeout_s = timeout_s

    def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        r = requests.get(
            f"{self.BASE_URL}/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=self.timeout_s,
        )
        payload = r.json()
        if isinstance(payload, dict) and int(payload.get("code", 0)) == -1121:
            raise UnsupportedSymbolError(f"Unsupported pair on Binance: {symbol}")
        r.raise_for_status()
        return {
            "symbol": symbol,
            "price": float(payload["price"]),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_historical_candles(self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1000) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        cursor = start_ms

        while cursor < end_ms:
            r = requests.get(
                f"{self.BASE_URL}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": limit,
                },
                timeout=self.timeout_s,
            )
            data = r.json()
            if isinstance(data, dict) and int(data.get("code", 0)) == -1121:
                raise UnsupportedSymbolError(f"Unsupported pair on Binance: {symbol}")
            r.raise_for_status()
            if not data:
                break

            for row in data:
                out.append(
                    {
                        "ts": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )

            last_open = int(data[-1][0])
            if len(data) < limit or last_open >= end_ms:
                break
            cursor = last_open + 1

        if not out:
            raise NoDataError(f"No data returned for {symbol} in requested range.")
        return out
